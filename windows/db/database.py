# db/database.py
#
# This file is the **data layer** of the app.
# It manages everything related to storing and retrieving information
# from the local SQLite database.
#
# The database has two main jobs:
#   1. Store **transactions** (each expense or income).
#   2. Store **recurring rules** (like “$100 rent every month”).
#
# Transactions are stored in cents (integers) instead of dollars/floats,
# so that rounding errors never corrupt money values.

from pathlib import Path
import sqlite3
from datetime import date, timedelta

# -------------------------------------------------------------------
# 1. Database file location
# -------------------------------------------------------------------
# The database is stored in a hidden folder in the user’s home directory.
# Example on Windows: C:\Users\<username>\.easybudget_desktop\easybudget.db
APP_DIR = Path.home() / ".easybudget_desktop"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "easybudget.db"

# -------------------------------------------------------------------
# 2. Base schema for database tables
# -------------------------------------------------------------------
# - transactions: stores each income/expense
# - recurring_rules: stores the “recipe” for repeating transactions
#
# Each recurring rule can generate many transactions.
#
# The UNIQUE index prevents duplicate auto-generated transactions.
SCHEMA_BASE = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,               -- format YYYY-MM-DD
  amount_cents INTEGER NOT NULL,    -- store in cents (e.g., $12.34 = 1234)
  note TEXT DEFAULT '',
  rule_id INTEGER                   -- points back to recurring_rules if auto-generated
);

CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);

CREATE TABLE IF NOT EXISTS recurring_rules(
  id INTEGER PRIMARY KEY,
  start_date TEXT NOT NULL,         -- first date the transaction occurs
  amount_cents INTEGER NOT NULL,
  note TEXT DEFAULT '',
  every_n INTEGER NOT NULL,         -- how often it repeats (e.g., 2)
  unit TEXT NOT NULL,               -- unit of repetition: 'day', 'week', or 'month'
  last_generated_date TEXT          -- remembers how far ahead we’ve generated
);
"""

# Keep one connection open for performance
_conn = None

# -------------------------------------------------------------------
# 3. Database connection helpers
# -------------------------------------------------------------------


def get_conn() -> sqlite3.Connection:
    """
    Return a cached SQLite connection with performance settings enabled.
    """
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row  # allows row["column"] access
        # Performance + reliability tweaks
        _conn.execute("PRAGMA foreign_keys = ON")
        _conn.execute("PRAGMA journal_mode = WAL")       # safe multi-access
        # balance speed & safety
        _conn.execute("PRAGMA synchronous = NORMAL")
        _conn.execute("PRAGMA temp_store = MEMORY")
        _conn.execute("PRAGMA cache_size = -4000")       # ~4MB memory cache
        # wait 3s if DB is locked
        _conn.execute("PRAGMA busy_timeout = 3000")
    return _conn


def migrate_if_needed():
    """
    Run schema creation and upgrades.
    This function is safe to call every time the app starts.
    """
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA_BASE)

        # Add missing rule_id column if database was created before it existed
        cols = [r["name"]
                for r in conn.execute("PRAGMA table_info('transactions')")]
        if "rule_id" not in cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN rule_id INTEGER")

        # Prevent duplicate generated rows
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_txn_unique
            ON transactions(date, amount_cents, note, rule_id)
        """)

# -------------------------------------------------------------------
# 4. Transactions API
# -------------------------------------------------------------------


def insert_txn(date_str: str, cents: int, note: str = "", rule_id=None) -> int:
    """
    Insert a transaction. If it’s part of a recurring series, include rule_id.
    Returns the transaction’s id.
    """
    conn = get_conn()
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO transactions(date, amount_cents, note, rule_id) VALUES (?,?,?,?)",
            (date_str, cents, note, rule_id),
        )
        if cur.lastrowid:  # successful insert
            return cur.lastrowid

        # If a duplicate already exists, return its id
        row = conn.execute(
            "SELECT id FROM transactions WHERE date=? AND amount_cents=? AND note=? AND (rule_id IS ? OR rule_id=?)",
            (date_str, cents, note, rule_id, rule_id),
        ).fetchone()
        return row["id"]


def update_txn(txn_id: int, date_str: str, cents: int, note: str = "") -> None:
    """Update an existing transaction by id."""
    conn = get_conn()
    with conn:
        conn.execute(
            "UPDATE transactions SET date=?, amount_cents=?, note=? WHERE id=?",
            (date_str, cents, note, txn_id),
        )


def delete_txn(txn_id: int) -> None:
    """Delete a transaction by id."""
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))


def list_by_date(day_iso: str):
    """Get all transactions for a single date."""
    conn = get_conn()
    return conn.execute(
        "SELECT id, date, amount_cents, note, rule_id "
        "FROM transactions WHERE date = ? ORDER BY id DESC",
        (day_iso,),
    ).fetchall()


def get_txn(txn_id: int):
    """Get a single transaction by id."""
    conn = get_conn()
    return conn.execute(
        "SELECT id, date, amount_cents, note, rule_id FROM transactions WHERE id=?",
        (txn_id,),
    ).fetchone()


def balance_on_or_before(day_iso: str) -> int:
    """Get the total balance up to and including the given date."""
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) AS bal FROM transactions WHERE date<=?",
        (day_iso,),
    ).fetchone()
    return row["bal"]

# -------------------------------------------------------------------
# 5. Recurring rules
# -------------------------------------------------------------------
# A recurring rule is a template for generating future transactions.
# Example: "$200 rent every 1 month starting 2025-01-01".
# The app generates transactions up to a “horizon” (e.g., 12 months ahead).


def create_rule(start_date: str, amount_cents: int, note: str, every_n: int, unit: str) -> int:
    """Create a recurring rule and return its id."""
    assert unit in ("day", "week", "month")
    conn = get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO recurring_rules(start_date, amount_cents, note, every_n, unit, last_generated_date) "
            "VALUES (?,?,?,?,?,NULL)",
            (start_date, amount_cents, note, every_n, unit),
        )
        return cur.lastrowid


def rules_all():
    """Return all recurring rules in the database."""
    return get_conn().execute("SELECT * FROM recurring_rules ORDER BY id").fetchall()


def delete_rule_and_txns(rule_id: int):
    """Delete a recurring rule and all of its generated transactions."""
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM transactions WHERE rule_id = ?", (rule_id,))
        conn.execute("DELETE FROM recurring_rules WHERE id = ?", (rule_id,))

# --- date helpers for monthly increments ---


def _add_months(d: date, months: int) -> date:
    """Add N months to a date (clamps the day to end-of-month if needed)."""
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last_day = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, last_day))


def _advance(d: date, every_n: int, unit: str) -> date:
    """Return the next occurrence of a recurring date."""
    if unit == "day":
        return d + timedelta(days=every_n)
    if unit == "week":
        return d + timedelta(weeks=every_n)
    if unit == "month":
        return _add_months(d, every_n)
    raise ValueError("invalid unit")


def generate_until(rule_id: int, until_date: str) -> None:
    """
    Generate transactions for a recurring rule until the given horizon.
    Uses INSERT OR IGNORE + UNIQUE index to avoid duplicates.
    """
    conn = get_conn()
    r = conn.execute("SELECT * FROM recurring_rules WHERE id=?",
                     (rule_id,)).fetchone()
    if not r:
        return

    start = date.fromisoformat(r["start_date"])
    every_n, unit = r["every_n"], r["unit"]
    amt, note = r["amount_cents"], r["note"]
    horizon = date.fromisoformat(until_date)

    cur = start if not r["last_generated_date"] else _advance(
        date.fromisoformat(r["last_generated_date"]), every_n, unit)

    last_created = None
    while cur <= horizon:
        insert_txn(cur.isoformat(), amt, note, rule_id=rule_id)
        last_created = cur
        cur = _advance(cur, every_n, unit)

    if last_created is not None:
        with conn:
            conn.execute(
                "UPDATE recurring_rules SET last_generated_date=? WHERE id=?",
                (last_created.isoformat(), rule_id),
            )


def coalesce_manual_start_into_rule(rule_id: int) -> None:
    """
    Handle duplicates when the user creates the first transaction manually
    AND also sets up a recurring rule for the same start date.

    This function merges the manual transaction into the recurring rule
    so that only one copy remains.
    """
    conn = get_conn()
    r = conn.execute("SELECT * FROM recurring_rules WHERE id=?",
                     (rule_id,)).fetchone()
    if not r:
        return

    start = r["start_date"]
    amt = r["amount_cents"]
    note = r["note"]

    # Look for a manual transaction on the same start date
    manual = conn.execute(
        "SELECT id FROM transactions WHERE date=? AND amount_cents=? AND note=? AND rule_id IS NULL LIMIT 1",
        (start, amt, note),
    ).fetchone()
    if not manual:
        return

    # If we already generated one, delete manual duplicate
    generated = conn.execute(
        "SELECT id FROM transactions WHERE date=? AND amount_cents=? AND note=? AND rule_id=? LIMIT 1",
        (start, amt, note, rule_id),
    ).fetchone()

    with conn:
        if generated:
            conn.execute("DELETE FROM transactions WHERE id=?",
                         (manual["id"],))
        else:
            conn.execute(
                "UPDATE transactions SET rule_id=? WHERE id=?", (rule_id, manual["id"]))
