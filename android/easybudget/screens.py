# easybudget/screens.py
#
# The three screens of the app:
#   HomeScreen      balance card, calendar, the selected day's transactions
#   EditScreen      add / edit an expense or income (one-off or recurring)
#   SettingsScreen  theme, currency, low balance warning, week start
#
# Layouts live in screens.kv; this file reacts to taps and talks to the
# database through the app object (see app.py).

import calendar
from datetime import date, timedelta

from kivy.app import App
from kivy.factory import Factory
from kivy.properties import (
    BooleanProperty, NumericProperty, ObjectProperty, StringProperty,
)
from kivy.uix.screenmanager import Screen

from . import database as db
from .dialogs import DatePickerSheet, choice_sheet, first_visible_day, weekday_names
from .formatting import (
    INTERVALS, compact_amount, format_money, interval_label, parse_amount,
)
from .widgets import TapCard, Toast, apply_key, pretty_amount


def long_date(d: date) -> str:
    return f"{d:%A}, {d:%B} {d.day}"


def short_date(d: date) -> str:
    text = f"{d:%a}, {d:%b} {d.day}"
    return text if d.year == date.today().year else f"{text}, {d.year}"


def month_bounds(year: int, month: int):
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    return first, last


# ---------------------------------------------------------------------------
# Home
# ---------------------------------------------------------------------------
class TxnItem(TapCard):
    txn_id = NumericProperty(0)
    title = StringProperty("")
    subtitle = StringProperty("")
    amount = StringProperty("")
    is_income = BooleanProperty(False)
    recurring = BooleanProperty(False)


class HomeScreen(Screen):
    today_selected = BooleanProperty(True)

    def on_kv_post(self, *_):
        self.ids.grid.bind(on_day=lambda _g, iso: self.select_day(iso),
                           on_swipe=lambda _g, direction: self.shift_month(direction))

    # --- navigation ---------------------------------------------------------
    def select_day(self, iso: str):
        app = App.get_running_app()
        d = date.fromisoformat(iso)
        app.selected = d
        app.view_year, app.view_month = d.year, d.month
        self.refresh()

    def shift_month(self, delta: int):
        app = App.get_running_app()
        idx = app.view_year * 12 + app.view_month - 1 + delta
        app.view_year, app.view_month = idx // 12, idx % 12 + 1
        today = date.today()
        if (today.year, today.month) == (app.view_year, app.view_month):
            app.selected = today
        else:
            app.selected = date(app.view_year, app.view_month, 1)
        self.refresh()

    def go_today(self):
        self.select_day(date.today().isoformat())

    # --- drawing ------------------------------------------------------------
    def refresh(self):
        app = App.get_running_app()
        y, m = app.view_year, app.view_month
        app.ensure_generated(y, m)

        month_start, month_end = month_bounds(y, m)
        first = first_visible_day(month_start, app.week_start)
        last = first + timedelta(days=41)
        balances = db.daily_balances(first.isoformat(), last.isoformat())

        amounts, statuses = {}, {}
        for iso, cents in balances.items():
            amounts[iso] = compact_amount(cents)
            statuses[iso] = app.balance_status(cents)

        ids = self.ids
        ids.month_title.text = f"{calendar.month_name[m]} {y}"
        for label, name in zip(ids.weekdays.children[::-1], weekday_names(app.week_start)):
            label.text = name
        ids.grid.show(first, m, app.selected.isoformat(), amounts, statuses)

        # Balance card
        sel_iso = app.selected.isoformat()
        balance = balances.get(sel_iso)
        if balance is None:
            balance = db.balance_on_or_before(sel_iso)
        today = date.today()
        ids.hero_label.text = ("Balance today" if app.selected == today
                               else f"Balance on {short_date(app.selected)}")
        ids.hero_amount.text = format_money(balance, app.currency)
        if balance < 0:
            ids.hero_status.text = "Below zero"
            ids.hero_status.icon = "alert-circle-outline"
        elif balance < app.low_balance:
            ids.hero_status.text = f"Below your {format_money(app.low_balance, app.currency)} warning"
            ids.hero_status.icon = "alert-outline"
        else:
            ids.hero_status.text = ""
        income, expense = db.period_totals(month_start.isoformat(), month_end.isoformat())
        month_abbr = calendar.month_abbr[m]
        ids.stat_in.label = f"Income · {month_abbr}"
        ids.stat_in.value = format_money(income, app.currency, plus=True)
        ids.stat_out.label = f"Expenses · {month_abbr}"
        ids.stat_out.value = format_money(expense, app.currency)

        # Transactions of the selected day
        rows = db.list_by_date(sel_iso)
        ids.day_title.text = long_date(app.selected)
        self.today_selected = app.selected == today
        if self.today_selected:
            ids.day_count.text = "Today"
        else:
            ids.day_count.text = (f"{len(rows)} entr{'y' if len(rows) == 1 else 'ies'}"
                                  if rows else "")
        box = ids.txn_list
        box.clear_widgets()
        if not rows:
            box.add_widget(Factory.EmptyDay())
        for r in rows:
            cents = r["amount_cents"]
            recurring = r["rule_id"] is not None
            item = TxnItem(
                txn_id=r["id"],
                title=r["note"] or ("Income" if cents > 0 else "Expense"),
                subtitle=(interval_label(r["every_n"], r["unit"]) or "Recurring")
                if recurring else "One-time",
                amount=format_money(cents, app.currency, plus=True),
                is_income=cents > 0,
                recurring=recurring,
            )
            item.bind(on_release=lambda it: app.open_txn_actions(it.txn_id))
            box.add_widget(item)


# ---------------------------------------------------------------------------
# Add / edit
# ---------------------------------------------------------------------------
class EditScreen(Screen):
    title = StringProperty("")
    kind = StringProperty("expense")          # 'expense' or 'income'
    amount_raw = StringProperty("")           # what was typed on the keypad
    amount_display = StringProperty("0")
    date_text = StringProperty("")
    show_interval = BooleanProperty(False)
    interval_text = StringProperty("")
    save_text = StringProperty("Save")
    the_date = ObjectProperty(date.today())

    def on_kv_post(self, *_):
        self.ids.kind.options = [
            {"key": "expense", "text": "Expense", "icon": "minus", "color": "negative"},
            {"key": "income", "text": "Income", "icon": "plus", "color": "positive"},
        ]
        self.ids.kind.bind(on_select=lambda _s, key: setattr(self, "kind", key))

    def setup(self, *, recurring=False, txn=None, scope=None, default_date=None):
        """
        New entry: setup(recurring=..., default_date=...)
        Edit:      setup(txn=row, scope='single' | 'future')
                   ('single' edits one transaction / one occurrence,
                    'future' edits this and all following occurrences)
        """
        self.txn = txn
        self.scope = scope
        self.recurring = recurring if txn is None else (scope == "future")
        self.every_n, self.unit = 1, "month"
        if txn is None:
            self.kind = "expense"
            self.amount_raw = ""
            self.the_date = default_date or date.today()
            self.ids.note.text = ""
        else:
            cents = txn["amount_cents"]
            self.kind = "income" if cents > 0 else "expense"
            whole, rest = divmod(abs(cents), 100)
            self.amount_raw = f"{whole}.{rest:02d}" if rest else str(whole)
            self.the_date = date.fromisoformat(txn["date"])
            self.ids.note.text = txn["note"] or ""
            if txn["every_n"]:
                self.every_n, self.unit = txn["every_n"], txn["unit"]
        self.ids.kind.value = self.kind
        self.show_interval = self.recurring
        self.on_the_date()      # refresh the label even if the date didn't change
        self._update_texts()

    # --- reactions ------------------------------------------------------------
    def on_kind(self, *_):
        self._update_texts()

    def on_amount_raw(self, *_):
        self.amount_display = pretty_amount(self.amount_raw)

    def on_the_date(self, *_):
        self.date_text = short_date(self.the_date)
        if self.the_date == date.today():
            self.date_text = f"Today · {self.date_text}"

    def _update_texts(self):
        noun = "income" if self.kind == "income" else "expense"
        if getattr(self, "txn", None) is None:
            self.title = f"New recurring {noun}" if self.recurring else f"New {noun}"
        elif self.scope == "future":
            self.title = f"Edit {noun} series"
        else:
            self.title = f"Edit {noun}"
        self.save_text = f"Save {noun}"
        self.interval_text = interval_label(self.every_n, self.unit)
        for label, n, unit, _badge in INTERVALS:
            if (n, unit) == (self.every_n, self.unit):
                self.interval_text = label

    def on_key(self, key):
        self.ids.note.ids.input.focus = False
        self.amount_raw = apply_key(self.amount_raw, key)

    def pick_date(self):
        self.ids.note.ids.input.focus = False
        app = App.get_running_app()
        DatePickerSheet(self.the_date, lambda d: setattr(self, "the_date", d),
                        week_start=app.week_start).open()

    def pick_interval(self):
        self.ids.note.ids.input.focus = False
        choices = [(i, label, "repeat", None) for i, (label, *_rest) in enumerate(INTERVALS)]
        current = next((i for i, (_l, n, u, _b) in enumerate(INTERVALS)
                        if (n, u) == (self.every_n, self.unit)), None)

        def _chosen(i):
            _label, self.every_n, self.unit, _badge = INTERVALS[i]
            self._update_texts()

        choice_sheet("Repeats", choices, _chosen, current=current)

    # --- save -----------------------------------------------------------------
    def save(self):
        app = App.get_running_app()
        try:
            cents = parse_amount(self.amount_raw)
        except ValueError as exc:
            Toast.show(str(exc), icon="alert-circle-outline")
            return
        if self.kind == "expense":
            cents = -cents
        note = self.ids.note.text.strip()
        day = self.the_date.isoformat()
        try:
            if self.txn is None and self.recurring:
                db.create_rule(day, cents, note, self.every_n, self.unit, app.horizon_iso())
                message = "Recurring entry added"
            elif self.txn is None:
                db.insert_txn(day, cents, note)
                message = "Income added" if cents > 0 else "Expense added"
            elif self.scope == "future":
                db.replace_rule_from(self.txn["rule_id"], self.txn["date"], day, cents, note,
                                     self.every_n, self.unit, app.horizon_iso())
                message = "Series updated"
            else:
                db.update_txn(self.txn["id"], day, cents, note)
                message = "Changes saved"
        except Exception as exc:
            Toast.show(f"Could not save: {exc}", icon="alert-circle-outline")
            return
        app.after_change(self.the_date, message)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class SettingRow(TapCard):
    icon = StringProperty("")
    title = StringProperty("")
    subtitle = StringProperty("")
    value = StringProperty("")
    chevron = BooleanProperty(True)


class SettingsScreen(Screen):
    def on_kv_post(self, *_):
        app = App.get_running_app()
        self.ids.theme_seg.options = [
            {"key": "system", "text": "System", "icon": "theme-light-dark"},
            {"key": "light", "text": "Light", "icon": "white-balance-sunny"},
            {"key": "dark", "text": "Dark", "icon": "weather-night"},
        ]
        self.ids.theme_seg.bind(on_select=lambda _s, key: app.set_theme_mode(key))
        self.ids.week_seg.options = [
            {"key": "sunday", "text": "Sunday"},
            {"key": "monday", "text": "Monday"},
        ]
        self.ids.week_seg.bind(on_select=lambda _s, key: app.set_week_start(key))

    def on_pre_enter(self, *_):
        self.refresh()

    def refresh(self):
        app = App.get_running_app()
        self.ids.theme_seg.value = app.theme_mode
        self.ids.week_seg.value = app.week_start
        self.ids.currency_row.value = app.currency.strip()
        self.ids.threshold_row.value = format_money(app.low_balance, app.currency)
