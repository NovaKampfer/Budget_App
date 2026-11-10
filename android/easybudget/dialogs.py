# easybudget/dialogs.py
#
# Bottom sheets used across the app: choice lists and menus, a date picker
# built on the same calendar as the home screen, an amount entry sheet with a
# keypad, a text entry sheet, and confirmations for destructive actions.

import calendar
from datetime import date, timedelta

from kivy.app import App
from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

from kivy.factory import Factory

from .widgets import (
    BottomSheet, Field, IconButton, Keypad, MonthPager, PrimaryButton, SheetRow, Text,
    TextButton, apply_key, pretty_amount,
)


def _buttons_row(*widgets):
    row = Factory.SheetButtons()
    for w in widgets:
        row.add_widget(w)
    return row


def choice_sheet(title, choices, on_choose, subtitle="", current=None):
    """
    choices: list of (key, text, icon, secondary) tuples.
    on_choose(key) is called after the user taps a row.
    """
    sheet = BottomSheet(title=title, subtitle=subtitle)
    for key, text, icon, secondary in choices:
        row = SheetRow(text=text, icon=icon or "", secondary=secondary or "",
                       checked=(current is not None and key == current))

        def _pick(_row, k=key):
            sheet.dismiss()
            on_choose(k)

        row.bind(on_release=_pick)
        sheet.body.add_widget(row)
    sheet.open()
    return sheet


def menu_sheet(title, items, subtitle=""):
    """
    items: list of dicts with keys text, icon, callback and optionally
    secondary (second line), checked (tick mark) and danger (red).
    """
    sheet = BottomSheet(title=title, subtitle=subtitle)
    for item in items:
        row = SheetRow(text=item["text"], icon=item.get("icon", ""),
                       secondary=item.get("secondary", ""),
                       checked=item.get("checked", False), danger=item.get("danger", False))

        def _run(_row, cb=item["callback"]):
            sheet.dismiss()
            cb()

        row.bind(on_release=_run)
        sheet.body.add_widget(row)
    sheet.open()
    return sheet


def text_sheet(title, subtitle, initial, hint, save_text, on_save, icon="text-short"):
    """
    Ask for a short piece of text (e.g. a profile name). Shown near the top of
    the screen so the keyboard never covers it. on_save(text) returns an error
    message to show, or None when the text was accepted.
    """
    app = App.get_running_app()
    sheet = BottomSheet(title=title, subtitle=subtitle, floating=True)
    field = Field(hint=hint, text=initial, icon=icon, height=dp(64))
    field.remove_widget(field.children[-1])          # no label above the box
    error = Text(color=app.pal.negative, font_size="13sp", size_hint_y=None, height=0,
                 padding=(dp(4), 0))
    cancel = TextButton(text="Cancel", muted=True)
    save = PrimaryButton(text=save_text, icon="check")

    def _save(*_):
        message = on_save(field.text)
        if message:
            error.text = message
            error.height = dp(24)
        else:
            field.ids.input.focus = False
            sheet.dismiss()

    cancel.bind(on_release=lambda *_: sheet.dismiss())
    save.bind(on_release=_save)
    field.ids.input.bind(on_text_validate=_save)

    def _clear_error(*_):
        error.text = ""
        error.height = 0

    field.ids.input.bind(text=_clear_error)
    for w in (field, error, _buttons_row(cancel, save)):
        sheet.body.add_widget(w)
    sheet.bind(on_dismiss=lambda *_: setattr(field.ids.input, "focus", False))
    sheet.open()
    Clock.schedule_once(lambda *_: setattr(field.ids.input, "focus", True), 0.3)
    return sheet


def action_sheet(title, subtitle, actions):
    """actions: list of (text, icon, callback, danger) tuples."""
    sheet = BottomSheet(title=title, subtitle=subtitle)
    for text, icon, callback, danger in actions:
        row = SheetRow(text=text, icon=icon, danger=danger)

        def _run(_row, cb=callback):
            sheet.dismiss()
            cb()

        row.bind(on_release=_run)
        sheet.body.add_widget(row)
    sheet.open()
    return sheet


def confirm_sheet(title, message, confirm_text, on_confirm, danger=True):
    app = App.get_running_app()
    sheet = BottomSheet(title=title, subtitle=message)
    cancel = TextButton(text="Cancel", muted=True)
    cancel.bind(on_release=lambda *_: sheet.dismiss())
    ok = PrimaryButton(text=confirm_text, icon="delete-outline" if danger else "check",
                       bg=app.pal.negative if danger else None,
                       fg=(app.pal.bg if app.is_dark else [1, 1, 1, 1]) if danger else None)

    def _ok(*_):
        sheet.dismiss()
        on_confirm()

    ok.bind(on_release=_ok)
    sheet.body.add_widget(_buttons_row(cancel, ok))
    sheet.open()
    return sheet


# ---------------------------------------------------------------------------
# Date picker
# ---------------------------------------------------------------------------
class DatePickerSheet(BottomSheet):
    def __init__(self, current: date, on_pick, week_start="sunday", **kwargs):
        super().__init__(title="Pick a date", **kwargs)
        self.on_pick = on_pick
        self.current = current
        self.view = date(current.year, current.month, 1)
        self.week_start = week_start

        header = BoxLayout(size_hint_y=None, height=dp(48))
        prev_btn = IconButton(icon="chevron-left", pos_hint={"center_y": .5})
        next_btn = IconButton(icon="chevron-right", pos_hint={"center_y": .5})
        self.month_label = Text(halign="center", font_size="17sp", bold=True)
        prev_btn.bind(on_release=lambda *_: self.pager.page(-1))
        next_btn.bind(on_release=lambda *_: self.pager.page(1))
        header.add_widget(prev_btn)
        header.add_widget(self.month_label)
        header.add_widget(next_btn)
        app = App.get_running_app()
        prev_btn.color = next_btn.color = app.pal.primary

        weekdays = BoxLayout(size_hint_y=None, height=dp(26))
        for name in weekday_names(week_start):
            weekdays.add_widget(Factory.WeekdayLabel(text=name))

        self.pager = MonthPager(row_height=dp(46))
        self.pager.provider = self.month_data
        self.pager.bind(on_day=lambda _p, iso: self._picked(iso),
                        on_page=lambda _p, delta: self.shift(delta))

        today_btn = TextButton(text="Today")
        today_btn.bind(on_release=lambda *_: self._picked(date.today().isoformat()))
        cancel_btn = TextButton(text="Cancel", muted=True)
        cancel_btn.bind(on_release=lambda *_: self.dismiss())

        for w in (header, weekdays, self.pager,
                  _buttons_row(Widget(), cancel_btn, today_btn)):
            self.body.add_widget(w)
        self.card.ids.scroll.swipe_target = self.pager
        self.refresh()

    def shift(self, months):
        idx = self.view.year * 12 + self.view.month - 1 + months
        self.view = date(idx // 12, idx % 12 + 1, 1)
        self.refresh()

    def month_data(self, delta=0):
        idx = self.view.year * 12 + self.view.month - 1 + delta
        month_start = date(idx // 12, idx % 12 + 1, 1)
        return dict(first_day=first_visible_day(month_start, self.week_start),
                    month=month_start.month, selected_iso=self.current.isoformat())

    def refresh(self):
        self.month_label.text = f"{calendar.month_name[self.view.month]} {self.view.year}"
        self.pager.show(**self.month_data())

    def _picked(self, iso):
        self.dismiss()
        self.on_pick(date.fromisoformat(iso))


def weekday_names(week_start: str):
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return names[-1:] + names[:-1] if week_start == "sunday" else names


def first_visible_day(month_start: date, week_start: str) -> date:
    start_weekday = 6 if week_start == "sunday" else 0   # Python: Monday == 0
    offset = (month_start.weekday() - start_weekday) % 7
    return month_start - timedelta(days=offset)


# ---------------------------------------------------------------------------
# Amount entry (adjust balance, low-balance threshold)
# ---------------------------------------------------------------------------
class AmountSheet(BottomSheet):
    def __init__(self, title, subtitle, initial_cents, on_save, allow_negative=False,
                 save_text="Save", **kwargs):
        super().__init__(title=title, subtitle=subtitle, **kwargs)
        app = App.get_running_app()
        self.app = app
        self.on_save = on_save
        self.negative = initial_cents < 0
        cents = abs(initial_cents)
        whole, rest = divmod(cents, 100)
        self.raw = (f"{whole}.{rest:02d}" if rest else str(whole)) if cents else ""

        display_row = BoxLayout(size_hint_y=None, height=dp(76), spacing=dp(8))
        self.sign_btn = IconButton(icon="plus-minus-variant", pos_hint={"center_y": .5})
        self.sign_btn.bind(on_release=self._toggle_sign)
        self.display = Text(halign="center", font_size="38sp", bold=True)
        if allow_negative:
            display_row.add_widget(self.sign_btn)
        display_row.add_widget(self.display)
        if allow_negative:
            display_row.add_widget(Widget(size_hint_x=None, width=dp(44)))

        keypad = Keypad(alt=True)
        keypad.bind(on_key=self._key)

        cancel = TextButton(text="Cancel", muted=True)
        cancel.bind(on_release=lambda *_: self.dismiss())
        save = PrimaryButton(text=save_text, icon="check")
        save.bind(on_release=self._save)

        for w in (display_row, keypad, _buttons_row(cancel, save)):
            self.body.add_widget(w)
        self._update()

    def _toggle_sign(self, *_):
        self.negative = not self.negative
        self._update()

    def _key(self, _keypad, key):
        self.raw = apply_key(self.raw, key)
        self._update()

    def _update(self):
        sign = "-" if self.negative and self.raw.strip("0.") else ""
        self.display.text = f"{sign}{self.app.currency}{pretty_amount(self.raw)}"
        if not self.raw:
            self.display.color = self.app.pal.text_muted
        else:
            self.display.color = self.app.pal.negative if sign else self.app.pal.text

    def _save(self, *_):
        try:
            text = self.raw or "0"
            whole, _dot, frac = text.partition(".")
            cents = int(whole or "0") * 100 + int((frac + "00")[:2])
        except ValueError:
            return
        if self.negative:
            cents = -cents
        self.dismiss()
        self.on_save(cents)
