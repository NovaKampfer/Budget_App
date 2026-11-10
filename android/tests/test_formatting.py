"""Tests for text formatting / parsing helpers."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from easybudget.formatting import (  # noqa: E402
    backup_json, compact_amount, format_money, interval_label, parse_amount, parse_signed_amount,
)


class TestFormatting(unittest.TestCase):
    def test_format_money(self):
        self.assertEqual(format_money(42600), "$426.00")
        self.assertEqual(format_money(-2500), "-$25.00")
        self.assertEqual(format_money(123456789, "€"), "€1,234,567.89")
        self.assertEqual(format_money(500, "$", plus=True), "+$5.00")
        self.assertEqual(format_money(0, "$", plus=True), "$0.00")

    def test_compact_amount(self):
        cases = {42600: "426", -400: "-4", 101600: "1,016", 999949: "9,999",
                 1234500: "12.3k", 1000000: "10k", 12345600: "123k", 99_940_000: "999k",
                 99_960_000: "1M", 123_456_700: "1.2M", -250_000_000: "-2.5M", 49: "0"}
        for cents, text in cases.items():
            self.assertEqual(compact_amount(cents), text, cents)

    def test_parse_amount(self):
        self.assertEqual(parse_amount("25"), 2500)
        self.assertEqual(parse_amount("25.5"), 2550)
        self.assertEqual(parse_amount(" $1,234.56 "), 123456)
        self.assertEqual(parse_amount("12,50"), 1250)
        self.assertEqual(parse_amount("1,234"), 123400)
        self.assertEqual(parse_amount("0.005"), 1)
        for bad in ("", ".", "0", "-5", "1.2.3"):
            with self.assertRaises(ValueError, msg=bad):
                parse_amount(bad)

    def test_parse_signed_amount(self):
        self.assertEqual(parse_signed_amount("-12.30"), -1230)
        self.assertEqual(parse_signed_amount("426"), 42600)
        self.assertEqual(parse_signed_amount("0"), 0)
        self.assertEqual(parse_signed_amount("0.00"), 0)
        with self.assertRaises(ValueError):
            parse_signed_amount("")

    def test_interval_label(self):
        self.assertEqual(interval_label(1, "day"), "Daily")
        self.assertEqual(interval_label(12, "month"), "Yearly")
        self.assertEqual(interval_label(5, "day"), "Every 5 days")
        self.assertEqual(interval_label(24, "month"), "Every 2 years")
        self.assertEqual(interval_label(None, None), "")

    def test_backup_json(self):
        import json
        data = {"app": "EasyBudget", "format": 1, "settings": {"currency": "€"},
                "accounts": [{"id": 1, "name": "Café"}], "recurring_rules": [],
                "transactions": [{"id": 1, "note": "a"}, {"id": 2, "note": None}]}
        text = backup_json(data)
        self.assertEqual(json.loads(text), data)
        self.assertIn('  {"id": 2, "note": null}', text.splitlines())   # one record per line
        self.assertIn("Café", text)


if __name__ == "__main__":
    unittest.main()
