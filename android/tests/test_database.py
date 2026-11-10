"""Tests for the data layer. Run from the android/ folder:  python -m unittest"""

import os
import sys
import tempfile
import unittest
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from easybudget import database as db  # noqa: E402


class DatabaseTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db.init(os.path.join(self.tmp.name, "test.db"))

    def tearDown(self):
        db.close()
        self.tmp.cleanup()

    def dates_for_rule(self, rule_id):
        return [r["date"] for r in db.conn().execute(
            "SELECT date FROM transactions WHERE rule_id=? ORDER BY date", (rule_id,))]


class TestOccurrences(unittest.TestCase):
    def test_monthly_rule_does_not_drift(self):
        start = date(2026, 1, 31)
        got = [db.nth_occurrence(start, 1, "month", k).isoformat() for k in range(5)]
        self.assertEqual(got, ["2026-01-31", "2026-02-28", "2026-03-31",
                               "2026-04-30", "2026-05-31"])

    def test_leap_year_and_yearly(self):
        start = date(2024, 2, 29)
        self.assertEqual(db.nth_occurrence(start, 12, "month", 1), date(2025, 2, 28))
        self.assertEqual(db.nth_occurrence(start, 12, "month", 4), date(2028, 2, 29))

    def test_occurrences_between_resumes_correctly(self):
        start = date(2026, 1, 1)
        first = db.occurrences_between(start, 2, "week", date(2025, 12, 31), date(2026, 2, 1))
        rest = db.occurrences_between(start, 2, "week", date(2026, 2, 1), date(2026, 3, 1))
        allx = db.occurrences_between(start, 2, "week", date(2025, 12, 31), date(2026, 3, 1))
        self.assertEqual(first + rest, allx)
        self.assertEqual([d.isoformat() for d in allx],
                         ["2026-01-01", "2026-01-15", "2026-01-29", "2026-02-12", "2026-02-26"])

    def test_month_end_resume(self):
        start = date(2026, 1, 31)
        got = db.occurrences_between(start, 1, "month", date(2026, 3, 30), date(2026, 5, 31))
        self.assertEqual([d.isoformat() for d in got], ["2026-03-31", "2026-04-30", "2026-05-31"])


class TestTransactions(DatabaseTestCase):
    def test_balances(self):
        db.insert_txn("2026-11-01", 50000, "Pay")
        db.insert_txn("2026-11-03", -2500, "Lunch")
        db.insert_txn("2026-11-03", -2500, "Lunch")  # identical one-offs are allowed
        self.assertEqual(db.balance_on_or_before("2026-11-02"), 50000)
        self.assertEqual(db.balance_on_or_before("2026-11-03"), 45000)
        bal = db.daily_balances("2026-10-31", "2026-11-04")
        self.assertEqual(bal["2026-10-31"], 0)
        self.assertEqual(bal["2026-11-02"], 50000)
        self.assertEqual(bal["2026-11-04"], 45000)
        self.assertEqual(db.period_totals("2026-11-01", "2026-11-30"), (50000, -5000))

    def test_list_by_date_orders_income_first(self):
        db.insert_txn("2026-11-03", -100, "a")
        db.insert_txn("2026-11-03", 900, "b")
        db.insert_txn("2026-11-03", -5000, "c")
        self.assertEqual([r["note"] for r in db.list_by_date("2026-11-03")], ["b", "a", "c"])

    def test_update_and_delete(self):
        tid = db.insert_txn("2026-11-03", -100, "a")
        db.update_txn(tid, "2026-11-04", -200, "b")
        row = db.get_txn(tid)
        self.assertEqual((row["date"], row["amount_cents"], row["note"]), ("2026-11-04", -200, "b"))
        self.assertIsNone(row["every_n"])
        db.delete_txn(tid)
        self.assertIsNone(db.get_txn(tid))

    def test_adjust_balance(self):
        db.insert_txn("2026-11-01", 10000, "x")
        self.assertEqual(db.adjust_balance("2026-11-09", 42600), 32600)
        self.assertEqual(db.balance_on_or_before("2026-11-09"), 42600)
        self.assertEqual(db.adjust_balance("2026-11-09", 42600), 0)

    def test_settings(self):
        self.assertEqual(db.get_setting("currency"), "$")
        db.set_setting("currency", "€")
        db.set_setting("currency", "£")
        self.assertEqual(db.get_setting("currency"), "£")


class TestRules(DatabaseTestCase):
    def test_generate_is_incremental_and_respects_deletions(self):
        rid = db.create_rule("2026-11-01", -2500, "Life", 1, "day", "2026-11-05")
        self.assertEqual(len(self.dates_for_rule(rid)), 5)
        victim = db.list_by_date("2026-11-03")[0]
        self.assertEqual(victim["every_n"], 1)
        db.delete_txn(victim["id"])
        db.generate_until(rid, "2026-11-10")
        dates = self.dates_for_rule(rid)
        self.assertNotIn("2026-11-03", dates)
        self.assertEqual(dates[-1], "2026-11-10")
        self.assertEqual(len(dates), 9)
        db.generate_until(rid, "2026-11-10")  # idempotent
        self.assertEqual(len(self.dates_for_rule(rid)), 9)

    def test_end_rule_before(self):
        rid = db.create_rule("2026-11-01", -100, "x", 1, "week", "2026-12-31")
        db.end_rule_before(rid, "2026-11-15")
        self.assertEqual(self.dates_for_rule(rid), ["2026-11-01", "2026-11-08"])
        db.generate_until(rid, "2027-06-30")  # must not come back
        self.assertEqual(self.dates_for_rule(rid), ["2026-11-01", "2026-11-08"])
        self.assertEqual(db.get_rule(rid)["end_date"], "2026-11-14")

    def test_end_rule_at_start_deletes_rule(self):
        rid = db.create_rule("2026-11-01", -100, "x", 1, "week", "2026-12-31")
        db.end_rule_before(rid, "2026-11-01")
        self.assertIsNone(db.get_rule(rid))
        self.assertEqual(self.dates_for_rule(rid), [])

    def test_replace_rule_from(self):
        rid = db.create_rule("2026-11-01", -100, "rent", 1, "month", "2027-02-28")
        new = db.replace_rule_from(rid, "2027-01-01", "2027-01-01", -150, "rent", 1, "month",
                                   "2027-02-28")
        self.assertEqual(self.dates_for_rule(rid), ["2026-11-01", "2026-12-01"])
        self.assertEqual(self.dates_for_rule(new), ["2027-01-01", "2027-02-01"])
        self.assertEqual(db.balance_on_or_before("2027-02-28"), -500)

    def test_replace_rule_moved_earlier_does_not_overlap(self):
        rid = db.create_rule("2026-11-01", -100, "x", 1, "day", "2026-11-10")
        new = db.replace_rule_from(rid, "2026-11-06", "2026-11-04", -100, "x", 1, "day",
                                   "2026-11-10")
        self.assertEqual(self.dates_for_rule(rid)[-1], "2026-11-03")
        self.assertEqual(self.dates_for_rule(new)[0], "2026-11-04")
        self.assertEqual(db.balance_on_or_before("2026-11-10"), -1000)

    def test_delete_rule(self):
        rid = db.create_rule("2026-11-01", -100, "x", 1, "day", "2026-11-10")
        db.insert_txn("2026-11-02", 500, "keep me")
        db.delete_rule(rid)
        self.assertEqual(db.balance_on_or_before("2026-12-01"), 500)

    def test_migrates_windows_database(self):
        # A database created by the Windows app has no end_date / settings.
        db.close()
        import sqlite3
        path = os.path.join(self.tmp.name, "old.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE transactions(id INTEGER PRIMARY KEY, date TEXT NOT NULL,
              amount_cents INTEGER NOT NULL, note TEXT DEFAULT '', rule_id INTEGER);
            CREATE TABLE recurring_rules(id INTEGER PRIMARY KEY, start_date TEXT NOT NULL,
              amount_cents INTEGER NOT NULL, note TEXT DEFAULT '', every_n INTEGER NOT NULL,
              unit TEXT NOT NULL, last_generated_date TEXT);
            INSERT INTO recurring_rules VALUES (1, '2026-11-01', -100, 'x', 1, 'day', '2026-11-03');
            INSERT INTO transactions VALUES (1, '2026-11-01', -100, 'x', 1);
            INSERT INTO transactions VALUES (2, '2026-11-02', -100, 'x', 1);
            INSERT INTO transactions VALUES (3, '2026-11-03', -100, 'x', 1);
        """)
        old.commit()
        old.close()
        db.init(path)
        db.generate_until(1, "2026-11-05")
        self.assertEqual(self.dates_for_rule(1)[-1], "2026-11-05")
        self.assertEqual(len(self.dates_for_rule(1)), 5)


if __name__ == "__main__":
    unittest.main()
