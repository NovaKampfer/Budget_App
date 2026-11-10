# easybudget/app.py
#
# The application object: owns the app-wide state (selected day, visible
# month, settings, theme) and the actions that more than one screen uses.

import json
from datetime import date
from pathlib import Path

from kivy.animation import Animation
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.lang import Builder
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.screenmanager import ScreenManager, SlideTransition
from kivymd.app import MDApp

from . import database as db
from .android_utils import (
    IS_ANDROID, enable_high_refresh_rate, set_system_bars, system_bar_overlap, system_prefers_dark,
)
from .dialogs import (
    AmountSheet, action_sheet, choice_sheet, confirm_sheet, menu_sheet, text_sheet,
)
from .files import open_text, save_text
from .formatting import CURRENCIES, backup_json, format_money, interval_label
from .screens import EditScreen, HomeScreen, SettingsScreen, month_bounds, short_date
from .theme import Palette, palette_values
from .widgets import Toast

__version__ = "1.2.0"

KV_DIR = Path(__file__).parent
AHEAD_MONTHS = 13      # recurring entries are generated this far past the visible month


class EasyBudgetApp(MDApp):
    pal = ObjectProperty(None)          # current colors (see theme.py)
    is_dark = BooleanProperty(False)
    inset_top = NumericProperty(0)      # space taken by system bars (edge-to-edge devices)
    inset_bottom = NumericProperty(0)
    currency = StringProperty("$")
    low_balance = NumericProperty(10000)
    week_start = StringProperty("sunday")
    theme_mode = StringProperty("system")
    version_name = StringProperty(__version__)
    account_name = StringProperty("")   # current profile, shortened for the top bar

    # ------------------------------------------------------------------ startup
    def build(self):
        self.title = "EasyBudget"
        db.init(Path(self.user_data_dir) / "easybudget.db")
        self._load_settings()
        self._update_account_name()

        self.is_dark = self._wants_dark()
        self.pal = Palette(dark=self.is_dark)
        self.theme_cls.primary_palette = "Teal"
        self.theme_cls.theme_style = "Dark" if self.is_dark else "Light"
        Window.clearcolor = self.pal.bg
        Window.softinput_mode = "below_target"

        today = date.today()
        self.selected = today
        self.view_year, self.view_month = today.year, today.month
        self._generated_until = None
        self._last_seen_day = today

        Builder.load_file(str(KV_DIR / "widgets.kv"))
        Builder.load_file(str(KV_DIR / "screens.kv"))
        self.sm = ScreenManager(transition=SlideTransition(duration=0.22))
        self.home = HomeScreen()
        self.editor = EditScreen()
        self.settings_screen = SettingsScreen()
        for screen in (self.home, self.editor, self.settings_screen):
            self.sm.add_widget(screen)
        return self.sm

    def on_start(self):
        Window.bind(on_keyboard=self._on_keyboard)
        set_system_bars(self.pal.bg, dark_icons=not self.is_dark)
        self._match_display_speed()
        self._update_insets()
        self.home.refresh()
        Clock.schedule_interval(self._follow_system_theme, 2.0)

    def on_pause(self):
        return True   # keep running in the background instead of restarting

    def on_resume(self):
        # Android/SDL calls this *before* it re-attaches the app's OpenGL
        # context. Creating widgets here (the refresh below builds new cards)
        # would touch the GPU without a context and crash the app, so do the
        # work on the next frame instead, when drawing works again.
        Clock.schedule_once(self._after_resume, 0.1)

    def _after_resume(self, *_):
        self._match_display_speed()       # Android may reset it while we're away
        self._update_insets()
        self._follow_system_theme()
        if date.today() != self._last_seen_day:      # the app was resumed on a new day
            self._last_seen_day = date.today()
            self.home.go_today()
        else:
            self.home.refresh()

    def _load_settings(self):
        self.currency = db.get_setting("currency") or "$"
        try:
            self.low_balance = int(db.get_setting("low_balance_cents"))
        except ValueError:
            self.low_balance = 10000
        self.week_start = db.get_setting("week_start")
        self.theme_mode = db.get_setting("theme")

    def _match_display_speed(self):
        """Draw as fast as the screen refreshes (Kivy's default cap is 60 fps,
        which looks choppy on 90/120 Hz phones). Kivy only redraws when
        something changed, so this costs nothing while the app is idle."""
        rate = enable_high_refresh_rate()
        Clock._max_fps = float(max(60, min(round(rate), 144)))

    def _update_insets(self):
        self.inset_top, self.inset_bottom = system_bar_overlap()

    # ------------------------------------------------------------------ theme
    def _wants_dark(self) -> bool:
        if self.theme_mode == "dark":
            return True
        if self.theme_mode == "light":
            return False
        return system_prefers_dark()

    def set_theme_mode(self, mode: str):
        self.theme_mode = mode
        db.set_setting("theme", mode)
        self.apply_theme()

    def toggle_theme(self):
        self.set_theme_mode("light" if self.is_dark else "dark")
        self.settings_screen.refresh()

    def apply_theme(self, animate=True):
        dark = self._wants_dark()
        if dark == self.is_dark:
            return
        self.is_dark = dark
        target = palette_values(dark)
        Animation.cancel_all(self.pal)
        if animate:
            Animation(d=0.3, t="out_quad", **target).start(self.pal)
        else:
            self.pal.apply(dark)
        self.theme_cls.theme_style = "Dark" if dark else "Light"
        Window.clearcolor = target["bg"]
        set_system_bars(target["bg"], dark_icons=not dark)

    def _follow_system_theme(self, *_):
        if self.theme_mode == "system" and IS_ANDROID:
            self.apply_theme()

    def balance_status(self, cents: int) -> str:
        if cents < 0:
            return "neg"
        if cents < self.low_balance:
            return "low"
        return "ok"

    # ------------------------------------------------------------------ data
    def horizon_iso(self) -> str:
        """Generate recurring entries up to this date."""
        today = date.today()
        y, m = max((self.view_year, self.view_month), (today.year, today.month))
        idx = y * 12 + m - 1 + AHEAD_MONTHS
        return month_bounds(idx // 12, idx % 12 + 1)[1].isoformat()

    def ensure_generated(self, *_):
        horizon = self.horizon_iso()
        if self._generated_until is None or horizon > self._generated_until:
            db.generate_all_until(horizon)
            self._generated_until = horizon

    def after_change(self, day: date, message: str):
        """Called after anything was saved: show that day and confirm."""
        self.selected = day
        self.view_year, self.view_month = day.year, day.month
        self.go_back()
        Toast.show(message)

    # ------------------------------------------------------------------ navigation
    def go(self, name: str):
        self.home.ids.dial.close()
        self.sm.transition.direction = "left"
        self.sm.current = name

    def go_back(self):
        if self.sm.current != "home":
            self.sm.transition.direction = "right"
            self.sm.current = "home"
        self.home.refresh()

    def open_settings(self, *_):
        self.go("settings")

    def open_editor(self, recurring=False, txn=None, scope=None):
        self.editor.setup(recurring=recurring, txn=txn, scope=scope, default_date=self.selected)
        self.go("edit")

    def _on_keyboard(self, _window, key, *_args):
        if key != 27:              # 27 = Escape on desktop, Back on Android
            return False
        if self.home.ids.dial.is_open:
            self.home.ids.dial.close()
            return True
        if self.sm.current != "home":
            self.go_back()
            return True
        return False               # Kivy then sends the app to the background

    # ------------------------------------------------------------------ transaction actions
    def open_txn_actions(self, txn_id: int):
        row = db.get_txn(txn_id)
        if row is None:
            self.home.refresh()
            return
        cents = row["amount_cents"]
        title = row["note"] or ("Income" if cents > 0 else "Expense")
        day = date.fromisoformat(row["date"])
        parts = [format_money(cents, self.currency, plus=True)]
        if row["rule_id"] is not None:
            parts.append(interval_label(row["every_n"], row["unit"]))
        parts.append(short_date(day))
        subtitle = "  ·  ".join(p for p in parts if p)

        if row["rule_id"] is None:
            actions = [
                ("Edit", "pencil-outline",
                 lambda: self.open_editor(txn=row, scope="single"), False),
                ("Delete", "delete-outline", lambda: self._delete_one(row), True),
            ]
        else:
            actions = [
                ("Edit this occurrence", "pencil-outline",
                 lambda: self.open_editor(txn=row, scope="single"), False),
                ("Edit this and future occurrences", "pencil-box-multiple-outline",
                 lambda: self.open_editor(txn=row, scope="future"), False),
                ("Delete this occurrence", "delete-outline",
                 lambda: self._delete_one(row), True),
                ("Delete this and future occurrences", "delete-sweep-outline",
                 lambda: self._confirm_delete_future(row, title), True),
                ("Delete all occurrences", "delete-forever-outline",
                 lambda: self._confirm_delete_all(row, title), True),
            ]
        action_sheet(title, subtitle, actions)

    def _delete_one(self, row):
        db.delete_txn(row["id"])
        self.home.refresh()
        Toast.show("Deleted", icon="delete-outline")

    def _confirm_delete_future(self, row, title):
        day = date.fromisoformat(row["date"])

        def _do():
            db.end_rule_before(row["rule_id"], row["date"])
            self.home.refresh()
            Toast.show("Future occurrences deleted", icon="delete-outline")

        confirm_sheet("Delete this and future ones?",
                      f"“{title}” stops repeating from {short_date(day)}. "
                      "Earlier entries are kept.", "Delete", _do)

    def _confirm_delete_all(self, row, title):
        def _do():
            db.delete_rule(row["rule_id"])
            self.home.refresh()
            Toast.show("Series deleted", icon="delete-outline")

        confirm_sheet("Delete the whole series?",
                      f"Every occurrence of “{title}”, past and future, is removed.",
                      "Delete all", _do)

    # ------------------------------------------------------------------ profiles
    def _update_account_name(self):
        name = db.get_account(db.current_account())["name"]
        self.account_name = name if len(name) <= 18 else name[:17].rstrip() + "\u2026"

    def open_profiles(self, *_):
        self.home.ids.dial.close()
        today = date.today().isoformat()
        current = db.current_account()
        accounts = db.list_accounts()
        items = []
        for a in accounts:
            balance = db.balance_on_or_before(today, account_id=a["id"])
            items.append(dict(
                text=a["name"], icon="wallet-outline", checked=a["id"] == current,
                secondary=f"Balance today: {format_money(balance, self.currency)}",
                callback=lambda account_id=a["id"]: self.switch_profile(account_id)))
        name = db.get_account(current)["name"]
        items.append(dict(text="Add a profile", icon="plus", callback=self.add_profile))
        items.append(dict(text=f"Rename \u201c{name}\u201d", icon="pencil-outline",
                          callback=self.rename_profile))
        if len(accounts) > 1:
            items.append(dict(text=f"Delete \u201c{name}\u201d", icon="delete-outline",
                              danger=True, callback=self.confirm_delete_profile))
        menu_sheet("Profiles", items,
                   subtitle="Each profile has its own transactions and balance.")

    def switch_profile(self, account_id: int, announce=True):
        db.set_current_account(account_id)
        self._update_account_name()
        self.home.refresh()
        if announce:
            Toast.show(f"Switched to {db.get_account(account_id)['name']}",
                       icon="swap-horizontal")

    def add_profile(self):
        def _save(name):
            try:
                account_id = db.create_account(name)
            except ValueError as exc:
                return str(exc)
            self.switch_profile(account_id, announce=False)
            Toast.show(f"Profile \u201c{db.get_account(account_id)['name']}\u201d created")
            return None

        text_sheet("New profile", "For example Work, Savings or a trip budget.", "",
                   "Profile name", "Create", _save, icon="wallet-outline")

    def rename_profile(self):
        current = db.current_account()

        def _save(name):
            try:
                db.rename_account(current, name)
            except ValueError as exc:
                return str(exc)
            self._update_account_name()
            Toast.show("Profile renamed")
            return None

        text_sheet("Rename profile", "", db.get_account(current)["name"], "Profile name",
                   "Save", _save, icon="wallet-outline")

    def confirm_delete_profile(self):
        current = db.current_account()
        name = db.get_account(current)["name"]

        def _do():
            db.delete_account(current)
            self._update_account_name()
            self.home.refresh()
            Toast.show(f"Deleted \u201c{name}\u201d", icon="delete-outline")

        confirm_sheet(f"Delete \u201c{name}\u201d?",
                      "All of its transactions and recurring entries are deleted. "
                      "This can't be undone.", "Delete profile", _do)

    # ------------------------------------------------------------------ backup
    def export_backup(self, *_):
        data = db.export_data()
        filename = f"EasyBudget-backup-{date.today().isoformat()}.json"

        def _done(saved, where, error):
            if saved:
                Toast.show(f"Backup saved to {where}" if where else "Backup saved",
                           icon="content-save-outline")
            elif error:
                Toast.show(f"Couldn't save: {error}", icon="alert-circle-outline")

        save_text(filename, backup_json(data), _done)

    def import_backup(self, *_):
        def _loaded(text, name, error):
            if text is None:
                if error:
                    Toast.show(f"Couldn't open the file: {error}", icon="alert-circle-outline")
                return
            try:
                data = json.loads(text)
            except ValueError:
                Toast.show("This file isn't an EasyBudget backup", icon="alert-circle-outline")
                return
            try:
                db.validate_backup(data)
            except ValueError as exc:
                Toast.show(str(exc), icon="alert-circle-outline")
                return
            confirm_sheet(
                "Restore this backup?",
                f"{name + ': ' if name else ''}{db.describe_backup(data)}. "
                "Everything currently in the app is replaced.",
                "Restore", lambda: self._restore(data), danger=True)

        open_text(_loaded)

    def _restore(self, data):
        try:
            db.import_data(data)
        except ValueError as exc:
            Toast.show(str(exc), icon="alert-circle-outline")
            return
        self._load_settings()
        self._update_account_name()
        self.apply_theme()
        self._generated_until = None
        self.selected = date.today()
        self.view_year, self.view_month = self.selected.year, self.selected.month
        self.settings_screen.refresh()
        self.home.refresh()
        Toast.show("Backup restored", icon="backup-restore")

    # ------------------------------------------------------------------ settings actions
    def open_adjust_balance(self, *_):
        self.home.ids.dial.close()
        today = date.today().isoformat()
        current = db.balance_on_or_before(today)

        def _save(cents):
            diff = db.adjust_balance(today, cents)
            self.selected = date.today()
            self.view_year, self.view_month = self.selected.year, self.selected.month
            self.home.refresh()
            Toast.show(f"Balance set to {format_money(cents, self.currency)}" if diff
                       else "Balance unchanged")

        AmountSheet("Adjust current balance",
                    f"Enter what your account holds today (now {format_money(current, self.currency)}).",
                    current, _save, allow_negative=True, save_text="Set balance").open()

    def edit_threshold(self, *_):
        def _save(cents):
            self.low_balance = cents
            db.set_setting("low_balance_cents", cents)
            self.settings_screen.refresh()
            self.home.refresh()

        AmountSheet("Low balance warning",
                    "Days whose balance drops below this are shown in orange.",
                    self.low_balance, _save).open()

    def pick_currency(self, *_):
        choices = [(symbol, f"{symbol.strip()}   {name}", None,
                    format_money(123456, symbol)) for name, symbol in CURRENCIES]

        def _chosen(symbol):
            self.currency = symbol
            db.set_setting("currency", symbol)
            self.settings_screen.refresh()
            self.home.refresh()

        choice_sheet("Currency", choices, _chosen, current=self.currency)

    def set_week_start(self, value: str):
        self.week_start = value
        db.set_setting("week_start", value)
        self.home.refresh()

    def on_stop(self):
        db.close()
