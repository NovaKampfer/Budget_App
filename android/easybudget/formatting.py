# easybudget/formatting.py
#
# Small pure helpers for turning numbers into text (and back).
# No Kivy imports here, so they are easy to unit test.

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# The repeat choices offered when adding a recurring entry.
# (menu label, every_n, unit, short badge shown in the list)
INTERVALS = [
    ("Every day", 1, "day", "Daily"),
    ("Every week", 1, "week", "Weekly"),
    ("Every 2 weeks", 2, "week", "Every 2 weeks"),
    ("Every 3 weeks", 3, "week", "Every 3 weeks"),
    ("Every 4 weeks", 4, "week", "Every 4 weeks"),
    ("Every month", 1, "month", "Monthly"),
    ("Every 2 months", 2, "month", "Every 2 months"),
    ("Every 3 months", 3, "month", "Quarterly"),
    ("Every 6 months", 6, "month", "Every 6 months"),
    ("Every year", 12, "month", "Yearly"),
]

# Currency symbols offered in Settings (all render with the bundled Roboto font).
CURRENCIES = [
    ("US / Canadian / Australian dollar", "$"),
    ("Euro", "€"),
    ("British pound", "£"),
    ("Japanese yen / Chinese yuan", "¥"),
    ("Indian rupee", "₹"),
    ("Korean won", "₩"),
    ("Brazilian real", "R$"),
    ("Swiss franc", "CHF "),
    ("Swedish / Norwegian / Danish krone", "kr "),
    ("Polish złoty", "zł "),
    ("South African rand", "R "),
    ("Philippine peso", "₱"),
    ("Nigerian naira", "₦"),
    ("Turkish lira", "₺"),
]


def format_money(cents: int, symbol: str = "$", plus: bool = False) -> str:
    """1234 -> '$12.34', -250000 -> '-$2,500.00'. plus=True adds '+' to income."""
    sign = "-" if cents < 0 else ("+" if plus and cents > 0 else "")
    dollars, rest = divmod(abs(int(cents)), 100)
    return f"{sign}{symbol}{dollars:,}.{rest:02d}"


def compact_amount(cents: int) -> str:
    """Short whole-number balance for calendar cells: 42600 -> '426', 1.2M -> '1.2M'."""
    whole = int((Decimal(int(cents)) / 100).to_integral_value(rounding=ROUND_HALF_UP))
    n = abs(whole)
    sign = "-" if whole < 0 else ""
    if n < 10_000:
        text = f"{n:,}"
    elif n < 99_950:
        text = f"{n / 1000:.1f}k".replace(".0k", "k")
    elif n < 999_500:
        text = f"{round(n / 1000)}k"
    else:
        text = f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    return sign + text


def parse_amount(text: str) -> int:
    """
    Parse what the user typed into cents. Accepts '12', '12.5', '12,50',
    '1,234.56' and ignores spaces / currency symbols. Raises ValueError.
    """
    s = "".join(ch for ch in (text or "") if ch.isdigit() or ch in ".,-")
    if s.startswith("-"):
        raise ValueError("Enter the amount without a sign")
    if "," in s and "." in s:
        s = s.replace(",", "")                     # 1,234.56
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = f"{head.replace(',', '')}.{tail}" if len(tail) <= 2 else s.replace(",", "")
    if not s or s == ".":
        raise ValueError("Enter an amount")
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ValueError("That doesn't look like a number") from None
    cents = int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents == 0:
        raise ValueError("Amount must be greater than zero")
    if cents > 99_999_999_999:
        raise ValueError("That amount is too large")
    return cents


def parse_signed_amount(text: str) -> int:
    """Like parse_amount but allows a leading minus sign and zero (for balances)."""
    raw = (text or "").strip()
    negative = raw.startswith("-")
    digits = raw.lstrip("-").strip()
    if digits.strip(" .,0") == "" and any(ch == "0" for ch in digits):
        return 0
    cents = parse_amount(digits)
    return -cents if negative else cents


def interval_label(every_n, unit) -> str:
    """Badge text for a recurring transaction, e.g. 'Monthly' or 'Every 5 days'."""
    if every_n is None or unit is None:
        return ""
    for _label, n, u, badge in INTERVALS:
        if n == every_n and u == unit:
            return badge
    if unit == "month" and every_n % 12 == 0:
        return f"Every {every_n // 12} years"
    return f"Every {every_n} {unit}s" if every_n != 1 else f"Every {unit}"
