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



class TestProfiles(DatabaseTestCase):
    def test_default_profile_exists(self):
        accounts = db.list_accounts()
        self.assertEqual([(a["id"], a["name"]) for a in accounts], [(1, "Personal")])
        self.assertEqual(db.current_account(), 1)

    def test_profiles_are_isolated(self):
        db.insert_txn("2026-11-01", 10000, "personal pay")
        work = db.create_account("Work")
        db.set_current_account(work)
        db.insert_txn("2026-11-01", 500, "work thing")
        rid = db.create_rule("2026-11-01", -100, "daily", 1, "day", "2026-11-05")
        self.assertEqual(db.balance_on_or_before("2026-11-05"), 500 - 500)
        self.assertEqual([r["note"] for r in db.list_by_date("2026-11-01")],
                         ["work thing", "daily"])
        self.assertEqual(db.period_totals("2026-11-01", "2026-11-30"), (500, -500))
        db.set_current_account(1)
        self.assertEqual(db.balance_on_or_before("2026-11-05"), 10000)
        self.assertEqual(db.daily_balances("2026-11-04", "2026-11-05")["2026-11-05"], 10000)
        self.assertEqual(db.balance_on_or_before("2026-11-05", account_id=work), 0)
        # rules keep generating into their own profile even when another is selected
        db.generate_until(rid, "2026-11-10")
        self.assertEqual(db.balance_on_or_before("2026-11-10"), 10000)
        self.assertEqual(db.balance_on_or_before("2026-11-10", account_id=work), 500 - 1000)

    def test_replace_rule_keeps_profile(self):
        work = db.create_account("Work")
        db.set_current_account(work)
        rid = db.create_rule("2026-11-01", -100, "x", 1, "day", "2026-11-10")
        db.set_current_account(1)
        new = db.replace_rule_from(rid, "2026-11-05", "2026-11-05", -200, "x", 1, "day",
                                   "2026-11-10")
        self.assertEqual(db.get_rule(new)["account_id"], work)
        self.assertEqual(db.balance_on_or_before("2026-11-10"), 0)

    def test_current_profile_is_remembered(self):
        work = db.create_account("Work")
        db.set_current_account(work)
        path = db.conn().execute("PRAGMA database_list").fetchone()["file"]
        db.init(path)
        self.assertEqual(db.current_account(), work)

    def test_names_are_validated(self):
        db.create_account("Work")
        for bad in ("", "   ", "work", "x" * 31):
            with self.assertRaises(ValueError, msg=bad):
                db.create_account(bad)
        db.rename_account(1, "  Home   budget ")
        self.assertEqual(db.get_account(1)["name"], "Home budget")
        db.rename_account(1, "HOME budget")          # same profile, different case is fine

    def test_delete_profile(self):
        with self.assertRaises(ValueError):
            db.delete_account(1)                     # the last one can't go
        work = db.create_account("Work")
        db.set_current_account(work)
        db.insert_txn("2026-11-01", 500, "w")
        db.create_rule("2026-11-01", -100, "d", 1, "day", "2026-11-05")
        db.delete_account(work)
        self.assertEqual(db.current_account(), 1)
        self.assertIsNone(db.get_account(work))
        self.assertEqual(db.conn().execute(
            "SELECT COUNT(*) FROM transactions WHERE account_id=?", (work,)).fetchone()[0], 0)
        self.assertEqual(db.rules_all(), [])

    def test_migrates_version_1_0_database(self):
        # Version 1.0 of the Android app had no profiles.
        db.close()
        import sqlite3
        path = os.path.join(self.tmp.name, "v10.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE transactions(id INTEGER PRIMARY KEY, date TEXT NOT NULL,
              amount_cents INTEGER NOT NULL, note TEXT DEFAULT '', rule_id INTEGER);
            CREATE TABLE recurring_rules(id INTEGER PRIMARY KEY, start_date TEXT NOT NULL,
              amount_cents INTEGER NOT NULL, note TEXT DEFAULT '', every_n INTEGER NOT NULL,
              unit TEXT NOT NULL, last_generated_date TEXT, end_date TEXT);
            CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            INSERT INTO settings VALUES ('currency', '€');
            INSERT INTO recurring_rules VALUES (1, '2026-11-01', -2500, 'Life', 1, 'day',
                                                '2026-11-02', NULL);
            INSERT INTO transactions VALUES (1, '2026-11-01', -2500, 'Life', 1);
            INSERT INTO transactions VALUES (2, '2026-11-02', -2500, 'Life', 1);
            INSERT INTO transactions VALUES (3, '2026-11-02', 30000, 'Pay', NULL);
        """)
        old.commit()
        old.close()
        db.init(path)
        self.assertEqual(db.get_setting("currency"), "€")
        self.assertEqual([a["name"] for a in db.list_accounts()], ["Personal"])
        self.assertEqual(db.balance_on_or_before("2026-11-02"), 25000)
        db.generate_until(1, "2026-11-04")
        self.assertEqual(db.balance_on_or_before("2026-11-04"), 20000)



class TestBackup(DatabaseTestCase):
    def _populate(self):
        db.set_setting("currency", "€")
        db.insert_txn("2026-11-01", 50000, "Pay")
        db.create_rule("2026-11-01", -2500, "Life", 1, "day", "2026-11-30")
        work = db.create_account("Work")
        db.set_current_account(work)
        db.insert_txn("2026-11-03", -999, "Lunch")
        db.create_rule("2026-11-02", -100, "Coffee", 1, "week", "2026-12-31")
        db.end_rule_before(db.rules_all()[-1]["id"], "2026-12-01")
        return work

    def test_round_trip(self):
        import json
        work = self._populate()
        before = db.export_data()
        text = json.dumps(before)
        # import into a brand-new database
        db.init(os.path.join(self.tmp.name, "other.db"))
        db.import_data(json.loads(text))
        after = db.export_data()
        for key in ("settings", "accounts", "recurring_rules", "transactions"):
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(db.current_account(), work)
        self.assertEqual(db.balance_on_or_before("2026-12-31"), -999 - 5 * 100)  # Nov 2,9,16,23,30
        # recurring rules keep generating after a restore
        db.generate_all_until("2027-01-31")
        rid = next(r["id"] for r in db.rules_all() if r["note"] == "Life")
        self.assertEqual(db.get_rule(rid)["last_generated_date"], "2027-01-31")

    def test_import_replaces_everything(self):
        self._populate()
        backup = db.export_data()
        db.create_account("Extra")
        db.set_current_account(1)
        db.insert_txn("2026-11-05", 123, "after backup")
        db.import_data(backup)
        self.assertEqual([a["name"] for a in db.list_accounts()], ["Personal", "Work"])
        self.assertFalse(any(t["note"] == "after backup" for t in db.export_data()["transactions"]))

    def test_bad_backups_change_nothing(self):
        self._populate()
        good = db.export_data()
        snapshot = db.export_data()
        import copy
        bad_cases = []
        for mutate in (
            lambda d: d.update(app="Other"),
            lambda d: d.update(format=99),
            lambda d: d.update(accounts=[]),
            lambda d: d["transactions"][0].update(date="2026-13-45"),
            lambda d: d["transactions"][0].update(account_id=999),
            lambda d: d["transactions"][0].update(amount_cents="12"),
            lambda d: d["recurring_rules"][0].update(unit="year"),
            lambda d: d["transactions"][0].update(rule_id=12345),
            lambda d: d.pop("transactions"),
        ):
            d = copy.deepcopy(good)
            mutate(d)
            bad_cases.append(d)
        bad_cases += [[], "text", None]
        for bad in bad_cases:
            with self.assertRaises(ValueError):
                db.import_data(bad)
            now = db.export_data()
            for key in ("settings", "accounts", "recurring_rules", "transactions"):
                self.assertEqual(snapshot[key], now[key])

    def test_describe(self):
        self._populate()
        text = db.describe_backup(db.export_data())
        self.assertTrue(text.startswith("2 profiles · "), text)
        self.assertIn("saved", text)


if __name__ == "__main__":
    unittest.main()
