# db/database.py
from pathlib import Path
import sqlite3
from datetime import date, timedelta

APP_DIR = Path.home() / ".easybudget_desktop"
APP_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = APP_DIR / "easybudget.db"

SCHEMA_BASE = """
PRAGMA foreign_keys = ON;

-- create tables if they don't exist (fresh installs get the new schema)
CREATE TABLE IF NOT EXISTS transactions(
  id INTEGER PRIMARY KEY,
  date TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  note TEXT DEFAULT '',
  rule_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);

CREATE TABLE IF NOT EXISTS recurring_rules(
  id INTEGER PRIMARY KEY,
  start_date TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  note TEXT DEFAULT '',
  every_n INTEGER NOT NULL,
  unit TEXT NOT NULL,               -- 'day' | 'week' | 'month'
  last_generated_date TEXT
);
"""

_conn = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH)
        _conn.row_factory = sqlite3.Row
    return _conn


def migrate_if_needed():
    """
    Bring the DB up to the latest schema.
    - Creates tables if missing
    - Adds 'rule_id' column to transactions if this DB was created before recurrence
    - Adds a UNIQUE index to prevent duplicate generated rows per rule
    """
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA_BASE)

        # Detect whether 'rule_id' exists on existing DBs
        cols = [r["name"]
                for r in conn.execute("PRAGMA table_info('transactions')")]
        if "rule_id" not in cols:
            conn.execute("ALTER TABLE transactions ADD COLUMN rule_id INTEGER")

        # Unique guard for generated rows (manual rows have NULL rule_id and can repeat)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_txn_unique
            ON transactions(date, amount_cents, note, rule_id)
        """)

# ---------- basic TX API ----------


def insert_txn(date_str: str, cents: int, note: str = "", rule_id: int | None = None) -> int:
    conn = get_conn()
    with conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO transactions(date, amount_cents, note, rule_id) VALUES (?,?,?,?)",
            (date_str, cents, note, rule_id),
        )
        if cur.lastrowid:
            return cur.lastrowid
        row = conn.execute(
            "SELECT id FROM transactions WHERE date=? AND amount_cents=? AND note=? AND (rule_id IS ? OR rule_id=?)",
            (date_str, cents, note, rule_id, rule_id),
        ).fetchone()
        return row["id"]


def update_txn(txn_id: int, date_str: str, cents: int, note: str = "") -> None:
    conn = get_conn()
    with conn:
        conn.execute(
            "UPDATE transactions SET date=?, amount_cents=?, note=? WHERE id=?",
            (date_str, cents, note, txn_id),
        )


def delete_txn(txn_id: int) -> None:
    conn = get_conn()
    with conn:
        conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))


def list_all():
    return get_conn().execute("SELECT * FROM transactions ORDER BY date, id").fetchall()


def list_by_date(day_iso: str):
    return get_conn().execute(
        "SELECT id, date, amount_cents, note FROM transactions WHERE date=? ORDER BY id DESC",
        (day_iso,),
    ).fetchall()


def get_txn(txn_id: int):
    return get_conn().execute(
        "SELECT id, date, amount_cents, note, rule_id FROM transactions WHERE id=?",
        (txn_id,),
    ).fetchone()


def balance_on_or_before(day_iso: str) -> int:
    row = get_conn().execute(
        "SELECT COALESCE(SUM(amount_cents),0) AS bal FROM transactions WHERE date<=?",
        (day_iso,),
    ).fetchone()
    return row["bal"]

# ---------- recurrence ----------


def create_rule(start_date: str, amount_cents: int, note: str, every_n: int, unit: str) -> int:
    assert unit in ("day", "week", "month")
    conn = get_conn()
    with conn:
        cur = conn.execute(
            "INSERT INTO recurring_rules(start_date, amount_cents, note, every_n, unit, last_generated_date) "
            "VALUES (?,?,?,?,?,NULL)",
            (start_date, amount_cents, note, every_n, unit),
        )
        return cur.lastrowid


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last_day = [31, 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0))
                else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m-1]
    return date(y, m, min(d.day, last_day))


def _advance(d: date, every_n: int, unit: str) -> date:
    from datetime import timedelta
    if unit == "day":
        return d + timedelta(days=every_n)
    if unit == "week":
        return d + timedelta(weeks=every_n)
    if unit == "month":
        return _add_months(d, every_n)
    raise ValueError("invalid unit")


def generate_until(rule_id: int, until_date: str) -> None:
    conn = get_conn()
    r = conn.execute("SELECT * FROM recurring_rules WHERE id=?",
                     (rule_id,)).fetchone()
    if not r:
        return
    start = date.fromisoformat(r["start_date"])
    every_n, unit = r["every_n"], r["unit"]
    amt, note = r["amount_cents"], r["note"]
    horizon = date.fromisoformat(until_date)

    cur = _advance(date.fromisoformat(r["last_generated_date"]), every_n, unit) \
        if r["last_generated_date"] else start

    changed = False
    while cur <= horizon:
        insert_txn(cur.isoformat(), amt, note, rule_id=rule_id)
        changed = True
        cur = _advance(cur, every_n, unit)

    if changed:
        # store “last generated” as the last date we actually inserted
        last_gen = _advance(cur, -every_n, unit)
        with conn:
            conn.execute("UPDATE recurring_rules SET last_generated_date=? WHERE id=?",
                         (last_gen.isoformat(), rule_id))
