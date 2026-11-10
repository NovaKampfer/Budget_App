# main.py
#
# EasyBudget Desktop (Offline)
# -------------------------------------------------------------
# WHAT THIS FILE DOES
# -------------------------------------------------------------
# This is the UI/interaction layer. It connects KivyMD widgets
# (calendar grid, buttons, dialogs) to the database functions
# in db/database.py.
#
# KEY IDEAS
# - The top banner shows the *ending balance* on the currently
#   selected day (sum of all transactions up to and including it).
# - The middle area is a month grid (Mon..Sun aligned). Each day
#   shows that day’s ending balance when reached via a running total.
# - The bottom list shows the transactions for the currently selected day.
# - The “+” button opens a dialog to add a one-off or recurring transaction.
# - Recurring rules generate future rows automatically and are marked "⟲".
#
# WHY KIVYMD
# - Gives Material Design components on top of Kivy.
# - Cross-platform UI with a single Python file for a simple desktop app.
#
# HOW RECURRENCE WORKS (high level)
# - When you create a rule (e.g., "every 2 weeks"), the app generates
#   future occurrences up to a *horizon* (configurable months ahead).
# - Each time we render a month, we extend all rules out to (current
#   month + horizon), using a UNIQUE index to avoid duplicates.
# - Deleting: you can delete a single occurrence or the entire rule.


from datetime import date, datetime, timedelta
import calendar
from functools import partial

from kivy.lang import Builder
from kivy.uix.widget import Widget

from kivymd.app import MDApp
from kivymd.uix.dialog import MDDialog
from kivymd.uix.button import MDRectangleFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.pickers import MDDatePicker
from kivymd.uix.selectioncontrol import MDSwitch
from kivymd.uix.menu import MDDropdownMenu
from kivymd.toast import toast
from kivymd.uix.list import OneLineListItem
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel

# Data layer: see db/database.py for definitions
from db.database import (
    migrate_if_needed,
    insert_txn, update_txn, delete_txn,
    get_txn, list_by_date, balance_on_or_before, get_conn,
    create_rule, generate_until, rules_all, delete_rule_and_txns,
    coalesce_manual_start_into_rule,
)


# -------------------------------------------------------------
# CONFIGURATION
# -------------------------------------------------------------
# How many months into the future to generate recurring items.
# (12 = generate a full year ahead. Increase to 24/36 if you prefer.)
AHEAD_N_MONTHS = 12

# A tiny cache: the farthest date (ISO) we've already generated up to.
# This prevents re-running generate_until(...) on every small refresh.
_generated_until_iso = None


# -------------------------------------------------------------
# SMALL, REUSABLE HELPERS
# -------------------------------------------------------------
def format_money(cents: int) -> str:
    """Return dollars-and-cents string for an integer cent value."""
    sign = "-" if cents < 0 else ""
    n = abs(cents)
    dollars, c = divmod(n, 100)
    return f"{sign}${dollars:,}.{c:02d}"


def notify(msg: str) -> None:
    """Show a small toast (fallback to print if toasts are unavailable)."""
    try:
        toast(msg)
    except Exception:
        print(f"[NOTICE] {msg}")


def end_of_month(y: int, m: int) -> date:
    """Return the last date of the given (year, month)."""
    return date(y, m, calendar.monthrange(y, m)[1])


def add_months(y: int, m: int, k: int):
    """
    Advance a (year, month) pair by k months and return the resulting (Y, M).
    This is for computing horizons without building full date objects yet.
    """
    idx = (y * 12 + (m - 1)) + k
    Y = idx // 12
    M = (idx % 12) + 1
    return Y, M


# -------------------------------------------------------------
# KV LAYOUT
# -------------------------------------------------------------
# We keep the KV here (inline) for a single-file app. It defines:
# - TopAppBar (title + month navigation)
# - Banner Label (shows selected day's ending balance)
# - Weekday header (Mon..Sun)
# - Month grid (7 columns; we populate it from Python)
# - Scrollable transaction list
# - Floating action button ("+")
KV = """
Screen:
    BoxLayout:
        orientation: "vertical"

        MDTopAppBar:
            id: topbar
            title: "EasyBudget"
            elevation: 2
            left_action_items: [["chevron-left", lambda x: app.prev_month()]]
            right_action_items: [["chevron-right", lambda x: app.next_month()]]

        MDLabel:
            id: banner
            text: "Balance on Today: $0.00"
            halign: "center"
            theme_text_color: "Custom"
            text_color: 0, 0.6, 0, 1
            size_hint_y: None
            height: "44dp"

        GridLayout:
            id: weekday_header
            cols: 7
            padding: "8dp"
            spacing: "6dp"
            size_hint_y: None
            height: self.minimum_height

            MDLabel:
                text: "Mon"
                halign: "center"
            MDLabel:
                text: "Tue"
                halign: "center"
            MDLabel:
                text: "Wed"
                halign: "center"
            MDLabel:
                text: "Thu"
                halign: "center"
            MDLabel:
                text: "Fri"
                halign: "center"
            MDLabel:
                text: "Sat"
                halign: "center"
            MDLabel:
                text: "Sun"
                halign: "center"

        GridLayout:
            id: month_grid
            cols: 7
            padding: "8dp"
            spacing: "6dp"
            size_hint_y: None
            height: self.minimum_height

        ScrollView:
            MDList:
                id: txn_list

        MDFloatingActionButton:
            icon: "plus"
            pos_hint: {"center_x": 0.92, "center_y": 0.10}
            on_release: app.open_add_dialog()
"""


# -------------------------------------------------------------
# APPLICATION CLASS
# -------------------------------------------------------------
class EasyBudgetApp(MDApp):
    """
    Owns the high-level application state and event handlers:
    - Current year/month being viewed
    - Currently selected date (ISO string)
    - Methods to build dialogs, respond to button presses, and render UI.
    """

    # ----- App bootstrap -----
    def build(self):
        """
        Runs once on startup:
        - Ensure the database schema exists.
        - Configure theme and build the root widget tree from KV.
        - Initialize current month and selected date to today.
        """
        migrate_if_needed()
        self.title = "EasyBudget Desktop (Offline)"
        self.theme_cls.primary_palette = "Teal"

        root = Builder.load_string(KV)

        today = date.today()
        self.current_year, self.current_month = today.year, today.month
        self._selected_iso = today.isoformat()

        return root

    def on_start(self):
        """
        Called when the window appears.
        We immediately render:
        - Top bar title (current month/year),
        - Banner (ending balance for selected day),
        - Month grid (with running balances).
        """
        self.refresh_month_title()
        self.refresh_today()
        self.refresh_month_grid()

    # ----- Month navigation (chevrons in the top bar) -----
    def prev_month(self):
        """Move the calendar view one month backward and refresh the UI."""
        y, m = self.current_year, self.current_month
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        self.current_year, self.current_month = y, m
        self._selected_iso = date(y, m, 1).isoformat()
        self.refresh_month_title()
        self.refresh_today()
        self.refresh_month_grid()

    def next_month(self):
        """Move the calendar view one month forward and refresh the UI."""
        y, m = self.current_year, self.current_month
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        self.current_year, self.current_month = y, m
        self._selected_iso = date(y, m, 1).isoformat()
        self.refresh_month_title()
        self.refresh_today()
        self.refresh_month_grid()

    # -------------------------------------------------------------
    # ADD TRANSACTION DIALOG (one-off or recurring)
    # -------------------------------------------------------------
    def open_add_dialog(self):
        """
        Build and show the "Add transaction" dialog.
        The dialog contains:
        - Amount field (float text)
        - Note field
        - Date button (opens a date picker)
        - Repeat toggle: if ON, shows "Every [N] [unit]"
        """
        # Initial state defaults: selected day, repeat OFF
        self._tx_date = date.fromisoformat(self._selected_iso)
        self._repeat_on, self._repeat_every, self._repeat_unit = False, 2, "week"

        # Content (Kivy widgets) constructed from KV snippet
        content = Builder.load_string("""
BoxLayout:
    orientation: "vertical"
    spacing: "10dp"
    padding: "8dp"
    size_hint_y: None
    height: "220dp"

    MDTextField:
        id: amount
        hint_text: "Amount (e.g., -15.00 or 1700)"
        input_filter: "float"
    MDTextField:
        id: note
        hint_text: "Description / Note"

    BoxLayout:
        size_hint_y: None
        height: "42dp"
        spacing: "8dp"
        MDLabel:
            text: "Repeat"
            halign: "left"
            valign: "center"
        MDSwitch:
            id: repeat_switch

    BoxLayout:
        size_hint_y: None
        height: "42dp"
        spacing: "8dp"
        MDTextField:
            id: every_n
            hint_text: "Every"
            input_filter: "int"
            text: ""
            helper_text: "Number"
            helper_text_mode: "on_focus"
            disabled: True
            size_hint_x: 0.35
        MDRectangleFlatButton:
            id: unit_btn
            text: "week"
            disabled: True
            size_hint_x: 0.45
""")

        # Date selector button shows the current date;
        # Clicking it opens MDDatePicker; saving updates the label.
        date_btn = MDRectangleFlatButton(
            text=self._tx_date.isoformat(),
            on_release=lambda *_: MDDatePicker(
                year=self._tx_date.year, month=self._tx_date.month, day=self._tx_date.day,
                on_save=self._on_add_date_saved
            ).open()
        )

        # The dialog has three buttons: date selector, Cancel, Save
        self._dialog = MDDialog(
            title="Add transaction",
            type="custom",
            content_cls=content,
            buttons=[
                date_btn,
                MDRectangleFlatButton(
                    text="Cancel", on_release=lambda *_: self._dialog.dismiss()),
                MDRectangleFlatButton(
                    text="Save", on_release=lambda *_: self._save_new_txn()),
            ],
        )

        # Field references for use in _save_new_txn()
        self._amount_field = content.ids.amount
        self._note_field = content.ids.note
        self._every_field = content.ids.every_n
        self._unit_btn = content.ids.unit_btn

        # Toggle logic: when Repeat is ON, enable "Every N" controls
        sw = content.ids.repeat_switch

        def _on_repeat(_inst, value):
            self._repeat_on = bool(value)
            self._every_field.disabled = not value
            self._unit_btn.disabled = not value
            if value and not self._every_field.text:
                self._every_field.text = str(self._repeat_every)
                self._unit_btn.text = self._repeat_unit

        sw.bind(active=_on_repeat)

        # Menu to choose the unit (day/week/month)
        menu_items = [
            {"text": "day",   "on_release": lambda: self._set_unit("day")},
            {"text": "week",  "on_release": lambda: self._set_unit("week")},
            {"text": "month", "on_release": lambda: self._set_unit("month")},
        ]
        self._unit_menu = MDDropdownMenu(
            caller=self._unit_btn, items=menu_items, width_mult=3)
        self._unit_btn.bind(on_release=lambda *_: self._unit_menu.open())

        self._dialog.open()

    def _set_unit(self, unit: str):
        """Update the unit button text and internal value when a unit is chosen."""
        self._repeat_unit = unit
        self._unit_btn.text = unit
        self._unit_menu.dismiss()

    def _on_add_date_saved(self, _picker, selected_date, *_):
        """
        Callback from the date picker: store the selected date and
        reflect it in the date button’s label.
        """
        self._tx_date = selected_date
        for b in self._dialog.buttons:
            if isinstance(b, MDRectangleFlatButton) and b.text.count("-") == 2:
                b.text = selected_date.isoformat()

    def _save_new_txn(self):
        """
        Validation + write:
        - Parse amount and note.
        - If repeat is ON: create a rule, coalesce a manual start row if any,
          and generate occurrences far into the future.
        - If repeat is OFF: insert a single transaction.
        """
        try:
            txt = (self._amount_field.text or "").strip()
            if not txt:
                notify("Please enter an amount")
                return
            cents = int(round(float(txt) * 100))
            note = (self._note_field.text or "").strip()

            if self._repeat_on:
                n_txt = (self._every_field.text or "").strip()
                if not n_txt:
                    notify("Please enter the repeat number")
                    return
                every_n = max(1, int(n_txt))
                unit = self._repeat_unit

                # Create the recurrence recipe
                rule_id = create_rule(
                    self._tx_date.isoformat(), cents, note, every_n, unit)

                # If the user had already inserted a manual row for that start date,
                # merge it into the rule to avoid duplicate first occurrence.
                coalesce_manual_start_into_rule(rule_id)

                # Generate far ahead: end of (current month + AHEAD_N_MONTHS)
                horizon_y, horizon_m = add_months(
                    self.current_year, self.current_month, AHEAD_N_MONTHS)
                horizon = end_of_month(horizon_y, horizon_m).isoformat()
                generate_until(rule_id, horizon)

            else:
                # Simple one-off transaction
                insert_txn(self._tx_date.isoformat(), cents, note)

        except Exception as e:
            notify(f"Error: {e}")
            return
        finally:
            if hasattr(self, "_dialog"):
                self._dialog.dismiss()

        # Select the saved date and refresh relevant views
        self._selected_iso = self._tx_date.isoformat()
        self.refresh_today()
        if self._date_in_current_month(self._selected_iso):
            self.refresh_month_grid()
        notify("Saved")

    # -------------------------------------------------------------
    # EDIT / DELETE DIALOGS
    # -------------------------------------------------------------
    def _open_edit_dialog(self, txn_id: int, *_):
        """
        Open a dialog to edit a transaction.
        If the row belongs to a recurring rule:
          - show buttons to delete ONLY THIS occurrence or the ENTIRE series.
        """
        row = get_txn(txn_id)
        if not row:
            notify("Transaction not found")
            return

        self._edit_txn_id = txn_id
        self._edit_date = datetime.fromisoformat(row["date"]).date()
        is_recur = row["rule_id"] is not None

        content = Builder.load_string("""
BoxLayout:
    orientation: "vertical"
    spacing: "8dp"
    padding: "8dp"
    size_hint_y: None
    height: "140dp"
    MDTextField:
        id: amount
        hint_text: "Amount"
        input_filter: "float"
    MDTextField:
        id: note
        hint_text: "Description / Note"
""")
        content.ids.amount.text = f"{row['amount_cents']/100:.2f}"
        content.ids.note.text = row["note"] or ""

        date_btn = MDRectangleFlatButton(
            text=row["date"],
            on_release=lambda *_: MDDatePicker(
                year=self._edit_date.year, month=self._edit_date.month, day=self._edit_date.day,
                on_save=self._on_edit_date_saved
            ).open()
        )

        # Buttons differ if this is a recurring row
        buttons = [date_btn]
        if is_recur:
            buttons += [
                MDRectangleFlatButton(
                    text="Delete this", on_release=lambda *_: self._delete_this_only(self._edit_txn_id)),
                MDRectangleFlatButton(
                    text="Delete series", on_release=lambda *_: self._delete_series(row["rule_id"])),
            ]
        else:
            buttons += [MDRectangleFlatButton(
                text="Delete", on_release=lambda *_: self._confirm_delete(self._edit_txn_id))]
        buttons += [
            MDRectangleFlatButton(
                text="Cancel", on_release=lambda *_: self._edit_dialog.dismiss()),
            MDRectangleFlatButton(
                text="Save",   on_release=lambda *_: self._save_edited_txn(content)),
        ]

        self._edit_dialog = MDDialog(
            title="Edit transaction", type="custom", content_cls=content, buttons=buttons)
        self._edit_dialog.open()

    def _on_edit_date_saved(self, _picker, selected_date, *_):
        """Store the edited date and update the button label inside the dialog."""
        self._edit_date = selected_date
        for b in self._edit_dialog.buttons:
            if isinstance(b, MDRectangleFlatButton) and b.text.count("-") == 2:
                b.text = selected_date.isoformat()

    def _save_edited_txn(self, content):
        """Persist changes to an existing transaction (amount, note, date)."""
        try:
            txt = (content.ids.amount.text or "").strip()
            if not txt:
                notify("Please enter an amount")
                return
            cents = int(round(float(txt) * 100))
            note = (content.ids.note.text or "").strip()
            update_txn(self._edit_txn_id,
                       self._edit_date.isoformat(), cents, note)
        except Exception as e:
            notify(f"Error: {e}")
            return
        finally:
            if hasattr(self, "_edit_dialog"):
                self._edit_dialog.dismiss()

        self._selected_iso = self._edit_date.isoformat()
        self.refresh_today()
        if self._date_in_current_month(self._selected_iso):
            self.refresh_month_grid()
        notify("Updated")

    def _delete_this_only(self, txn_id: int):
        """Delete only this occurrence (for both one-off and recurring rows)."""
        try:
            delete_txn(txn_id)
        except Exception as e:
            notify(f"Delete failed: {e}")
            return
        finally:
            if hasattr(self, "_edit_dialog"):
                self._edit_dialog.dismiss()

        self.refresh_today()
        if self._date_in_current_month(self._selected_iso):
            self.refresh_month_grid()
        notify("Deleted")

    def _delete_series(self, rule_id: int):
        """
        Delete all occurrences that belong to a recurring rule,
        and remove the rule itself.
        """
        try:
            delete_rule_and_txns(rule_id)
        except Exception as e:
            notify(f"Delete series failed: {e}")
            return
        finally:
            if hasattr(self, "_edit_dialog"):
                self._edit_dialog.dismiss()

        self.refresh_today()
        if self._date_in_current_month(self._selected_iso):
            self.refresh_month_grid()
        notify("Series deleted")

    def _confirm_delete(self, txn_id: int):
        """Small wrapper to unify delete actions from different buttons."""
        self._delete_this_only(txn_id)

    # -------------------------------------------------------------
    # RENDERING HELPERS
    # -------------------------------------------------------------
    def _date_in_current_month(self, iso: str) -> bool:
        """Return True if the given ISO date is in the currently viewed month."""
        d = datetime.fromisoformat(iso).date()
        return (d.year == self.current_year) and (d.month == self.current_month)

    def refresh_month_title(self):
        """Update the top app bar to show 'MonthName Year'."""
        self.root.ids.topbar.title = f"{calendar.month_name[self.current_month]} {self.current_year}"

    def refresh_today(self):
        """
        Update the banner and transaction list for the currently selected day.
        This function catches exceptions to avoid crashing the UI due to bad data.
        """
        try:
            iso = self._selected_iso

            # 1) Banner: ending balance on selected day (sum of all <= date)
            ending_cents = balance_on_or_before(iso)
            d = datetime.fromisoformat(iso)
            banner = self.root.ids.banner
            banner.text = f"Balance on {d.strftime('%b %d')}: {format_money(ending_cents)}"
            banner.text_color = (
                0, 0.6, 0, 1) if ending_cents >= 0 else (0.8, 0, 0, 1)

            # 2) Transaction list for that date
            rows = list_by_date(iso)
            lst = self.root.ids.txn_list
            lst.clear_widgets()

            for r in rows:
                # sqlite3.Row behaves like a mapping; use key membership (no .get on Row)
                is_recur = ("rule_id" in r.keys()) and (
                    r["rule_id"] is not None)
                prefix = "⟲ " if is_recur else ""
                text = f"{prefix}{format_money(r['amount_cents'])} — {r['note'] or ''}"

                item = OneLineListItem(text=text)
                item.theme_text_color = "Custom"
                item.text_color = (
                    0, 0.6, 0, 1) if r["amount_cents"] >= 0 else (0.8, 0, 0, 1)

                # Bind the click to open the edit dialog for this row
                # Use partial to pass the id as the first argument; ignore the widget param
                item.bind(on_release=partial(
                    self._open_edit_dialog, int(r["id"])))
                lst.add_widget(item)

        except Exception as e:
            notify(f"refresh_today error: {e}")
            import traceback
            traceback.print_exc()

    def refresh_month_grid(self):
        """
        (Re)build the visible month grid:
        - Extend all recurring rules to a far horizon (cached so we don't repeat work).
        - Compute the running balance and paint each day cell.
        - Make each day cell tappable: tapping selects that date and refreshes the list.
        """
        global _generated_until_iso

        y, m = self.current_year, self.current_month
        first = date(y, m, 1)

        # 1) Extend all rules to far horizon only if we haven't done so already.
        far_y, far_m = add_months(y, m, AHEAD_N_MONTHS)
        far_horizon = end_of_month(far_y, far_m).isoformat()
        if _generated_until_iso is None or far_horizon > _generated_until_iso:
            for r in rules_all():
                generate_until(r["id"], far_horizon)
            _generated_until_iso = far_horizon

        # 2) Query just what we need to paint the month grid.
        conn = get_conn()
        grid = self.root.ids.month_grid
        grid.clear_widgets()

        # Start the running balance from the day *before* this month begins.
        running = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) FROM transactions WHERE date <= ?",
            ((first - timedelta(days=1)).isoformat(),)
        ).fetchone()[0]

        last = end_of_month(y, m)
        rows = conn.execute(
            "SELECT date, SUM(amount_cents) AS total FROM transactions WHERE date BETWEEN ? AND ? GROUP BY date",
            (first.isoformat(), last.isoformat())
        ).fetchall()
        day_totals = {r["date"]: r["total"] for r in rows}

        # 3) Add leading blanks to align the 1st under the correct weekday (Mon=0..Sun=6).
        for _ in range(first.weekday()):
            grid.add_widget(Widget(size_hint_y=None, height="56dp"))

        # 4) Walk each day, update the running balance, and build a small card.
        dcur = first
        while dcur <= last:
            running += day_totals.get(dcur.isoformat(), 0)

            card = MDCard(
                orientation="vertical",
                size_hint_y=None, height="56dp", padding="6dp",
                radius=[10], md_bg_color=(.96, .96, .96, 1), ripple_behavior=True,
            )
            # Day number
            card.add_widget(MDLabel(
                text=str(dcur.day),
                font_style="Caption",
                theme_text_color="Secondary",
                size_hint_y=None, height="14dp",
            ))
            # Ending balance for this day
            card.add_widget(MDLabel(
                text=format_money(running),
                theme_text_color="Custom",
                text_color=(0, .6, 0, 1) if running >= 0 else (.8, 0, 0, 1),
                font_size="12sp",
            ))

            iso = dcur.isoformat()

            # Make the card tappable to select the day and update the list below.
            def _on_touch_up(instance, touch, _iso=iso):
                if instance.collide_point(*touch.pos):
                    self._selected_iso = _iso
                    self.refresh_today()
                return False  # don't swallow other events

            card.bind(on_touch_up=_on_touch_up)
            grid.add_widget(card)
            dcur += timedelta(days=1)


# -------------------------------------------------------------
# STANDARD PYTHON ENTRY POINT
# -------------------------------------------------------------
# Allows running this file directly (e.g., `python main.py`)
if __name__ == "__main__":
    EasyBudgetApp().run()
