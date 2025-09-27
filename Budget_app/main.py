# main.py
# EasyBudget (Desktop - Offline)
# -------------------------------------------------------------
# - Month view with ENDING balances per day (green/red)
# - Prev/next month navigation, aligned Mon..Sun
# - Select a day to view transactions
# - Add transaction (+) with optional recurrence:
#       Repeat: ON → Every [N] [Day|Week|Month]
# - Edit/Delete a transaction by tapping a list item
# - Notifications use toast (stable across KivyMD builds)
# -------------------------------------------------------------

from datetime import date, datetime, timedelta
import calendar

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

# --- data layer ---
from db.database import (
    migrate_if_needed,
    insert_txn, update_txn, delete_txn,
    get_txn, list_by_date, balance_on_or_before, get_conn,
    create_rule, generate_until
)

# ---------- helpers ----------


def format_money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    v = abs(cents)
    return f"{sign}${v//100:,}.{v % 100:02d}"


def notify(msg: str) -> None:
    try:
        toast(msg)
    except Exception:
        print(f"[NOTICE] {msg}")


# ---------- KV layout ----------
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

# ---------- main app ----------


class EasyBudgetApp(MDApp):
    def build(self):
        migrate_if_needed()
        self.title = "EasyBudget Desktop (Offline)"
        self.theme_cls.primary_palette = "Teal"
        root = Builder.load_string(KV)

        today = date.today()
        self.current_year = today.year
        self.current_month = today.month
        self._selected_iso = today.isoformat()
        return root

    def on_start(self):
        self.refresh_month_title()
        self.refresh_today()
        self.refresh_month_grid()

    # ---- month navigation ----
    def prev_month(self):
        y, m = self.current_year, self.current_month
        if m == 1:
            y, m = y - 1, 12
        else:
            m -= 1
        self.current_year, self.current_month = y, m
        self._selected_iso = date(y, m, 1).isoformat()
        self.refresh_month_title()
        self.refresh_today()
        self.refresh_month_grid()

    def next_month(self):
        y, m = self.current_year, self.current_month
        if m == 12:
            y, m = y + 1, 1
        else:
            m += 1
        self.current_year, self.current_month = y, m
        self._selected_iso = date(y, m, 1).isoformat()
        self.refresh_month_title()
        self.refresh_today()
        self.refresh_month_grid()

    # ---- add transaction (with recurrence) ----
    def open_add_dialog(self):
        """Add a transaction on the currently selected day; optional recurrence."""
        self._tx_date = date.fromisoformat(self._selected_iso)
        self._repeat_on = False            # switch off by default
        self._repeat_every = 2             # sensible default
        self._repeat_unit = "week"         # 'day' | 'week' | 'month'

        # Dialog content: amount, note, repeat toggle, every [N], unit chooser
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

        # Date selector button (left-most dialog button)
        date_btn = MDRectangleFlatButton(
            text=self._tx_date.isoformat(),
            on_release=lambda *_: MDDatePicker(
                year=self._tx_date.year, month=self._tx_date.month, day=self._tx_date.day,
                on_save=self._on_add_date_saved
            ).open()
        )

        # Build the dialog (Save uses _save_new_txn that also handles recurrence)
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
        # keep refs
        self._amount_field = content.ids.amount
        self._note_field = content.ids.note
        self._every_field = content.ids.every_n
        self._unit_btn = content.ids.unit_btn
        repeat_switch = content.ids.repeat_switch

        # Wire the repeat switch to enable/disable fields
        def _on_repeat_switch(_instance, value):
            self._repeat_on = bool(value)
            self._every_field.disabled = not value
            self._unit_btn.disabled = not value
            # Seed defaults when toggled on
            if value and not self._every_field.text:
                self._every_field.text = str(self._repeat_every)
                self._unit_btn.text = self._repeat_unit
        repeat_switch.bind(active=_on_repeat_switch)

        # Dropdown menu for unit selection
        menu_items = [
            {"text": "day",   "on_release": lambda: self._set_unit("day")},
            {"text": "week",  "on_release": lambda: self._set_unit("week")},
            {"text": "month", "on_release": lambda: self._set_unit("month")},
        ]
        self._unit_menu = MDDropdownMenu(
            caller=self._unit_btn,
            items=menu_items,
            width_mult=3,
        )
        self._unit_btn.bind(on_release=lambda *_: self._unit_menu.open())

        self._dialog.open()

    def _set_unit(self, unit: str):
        """Handle choosing day/week/month in the dropdown."""
        self._repeat_unit = unit
        self._unit_btn.text = unit
        self._unit_menu.dismiss()

    def _on_add_date_saved(self, _picker, selected_date, *_):
        self._tx_date = selected_date
        for b in self._dialog.buttons:
            if isinstance(b, MDRectangleFlatButton) and b.text.count("-") == 2:
                b.text = selected_date.isoformat()

    def _save_new_txn(self):
        """Insert the transaction; if Repeat ON, create rule and materialize future rows."""
        try:
            txt = (self._amount_field.text or "").strip()
            if not txt:
                notify("Please enter an amount")
                return
            cents = int(round(float(txt) * 100))
            note = (self._note_field.text or "").strip()

            # Save the initial transaction (always)
            insert_txn(self._tx_date.isoformat(), cents, note)

            # If recurrence is enabled: read "Every N" and "unit", create a rule
            if self._repeat_on:
                # Validate "every N"
                n_txt = (self._every_field.text or "").strip()
                if not n_txt:
                    notify("Please enter the repeat number")
                    return
                every_n = max(1, int(n_txt))
                unit = self._repeat_unit  # 'day'|'week'|'month'

                # Store a rule using the chosen date as start_date
                rule_id = create_rule(
                    start_date=self._tx_date.isoformat(),
                    amount_cents=cents,
                    note=note,
                    every_n=every_n,
                    unit=unit,
                )

                # Generate up to end of the currently shown month (inclusive)
                end_of_month = date(self.current_year, self.current_month,
                                    calendar.monthrange(self.current_year, self.current_month)[1]).isoformat()
                generate_until(rule_id, end_of_month)

        except Exception as e:
            notify(f"Error: {e}")
            return
        finally:
            if hasattr(self, "_dialog"):
                self._dialog.dismiss()

        # Keep selected day on the new txn date; refresh UI and month grid
        self._selected_iso = self._tx_date.isoformat()
        self.refresh_today()
        self.refresh_month_grid()
        notify("Saved")

    # ---- edit/delete (single occurrences) ----
    def _open_edit_dialog(self, txn_id: int):
        row = get_txn(txn_id)
        if not row:
            notify("Transaction not found")
            return
        self._edit_txn_id = txn_id
        self._edit_date = datetime.fromisoformat(row["date"]).date()

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
        self._edit_dialog = MDDialog(
            title="Edit transaction",
            type="custom",
            content_cls=content,
            buttons=[
                date_btn,
                MDRectangleFlatButton(
                    text="Delete", on_release=lambda *_: self._confirm_delete(txn_id)),
                MDRectangleFlatButton(
                    text="Cancel", on_release=lambda *_: self._edit_dialog.dismiss()),
                MDRectangleFlatButton(
                    text="Save", on_release=lambda *_: self._save_edited_txn(content)),
            ],
        )
        self._edit_dialog.open()

    def _on_edit_date_saved(self, _picker, selected_date, *_):
        self._edit_date = selected_date
        for b in self._edit_dialog.buttons:
            if isinstance(b, MDRectangleFlatButton) and b.text.count("-") == 2:
                b.text = selected_date.isoformat()

    def _save_edited_txn(self, content):
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
        self.refresh_month_grid()
        notify("Updated")

    def _confirm_delete(self, txn_id: int):
        try:
            delete_txn(txn_id)
        except Exception as e:
            notify(f"Delete failed: {e}")
            return
        finally:
            if hasattr(self, "_edit_dialog"):
                self._edit_dialog.dismiss()
        self.refresh_today()
        self.refresh_month_grid()
        notify("Deleted")

    # ---- rendering helpers ----
    def refresh_month_title(self):
        self.root.ids.topbar.title = f"{calendar.month_name[self.current_month]} {self.current_year}"

    def refresh_today(self):
        iso = self._selected_iso
        ending_cents = balance_on_or_before(iso)
        d = datetime.fromisoformat(iso)
        banner = self.root.ids.banner
        banner.text = f"Balance on {d.strftime('%b %d')}: {format_money(ending_cents)}"
        banner.text_color = (
            0, 0.6, 0, 1) if ending_cents >= 0 else (0.8, 0, 0, 1)

        rows = list_by_date(iso)
        lst = self.root.ids.txn_list
        lst.clear_widgets()
        for r in rows:
            item = OneLineListItem(
                text=f"{format_money(r['amount_cents'])} — {r['note'] or ''}")
            item.theme_text_color = "Custom"
            item.text_color = (
                0, 0.6, 0, 1) if r["amount_cents"] >= 0 else (0.8, 0, 0, 1)
            item.bind(on_release=lambda _inst,
                      _id=r["id"]: self._open_edit_dialog(_id))
            lst.add_widget(item)

    def refresh_month_grid(self):
        """7-column month grid with ENDING balance per day, aligned to weekdays.
           Also: if there are recurring rules, auto-generate rows up to this month’s end.
        """
        conn = get_conn()
        y, m = self.current_year, self.current_month
        first = date(y, m, 1)
        last = date(y, m, calendar.monthrange(y, m)[1])

        # Generate recurring rows up to the end of this month (idempotent)
        # We do it here so navigating months shows projected income/expenses.
        # (We don't need the rule list; generate_until is idempotent when called from saving rule,
        # but if you add rules earlier, this keeps grid consistent.)
        # NOTE: no global rule list call here—generation is done when rules are created;
        # if you later want "Regenerate all", we could add a loop over rules_all().
        # For now, generation occurs on save and is sufficient.

        grid = self.root.ids.month_grid
        grid.clear_widgets()

        # Starting balance = sum up to day BEFORE the first
        running = conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) FROM transactions WHERE date <= ?",
            ((first - timedelta(days=1)).isoformat(),)
        ).fetchone()[0]

        # Totals per day inside this month
        rows = conn.execute(
            "SELECT date, SUM(amount_cents) AS total FROM transactions WHERE date BETWEEN ? AND ? GROUP BY date",
            (first.isoformat(), last.isoformat())
        ).fetchall()
        day_totals = {r["date"]: r["total"] for r in rows}

        # leading spacers to align the first day
        for _ in range(first.weekday()):
            grid.add_widget(Widget(size_hint_y=None, height="56dp"))

        dcur = first
        while dcur <= last:
            running += day_totals.get(dcur.isoformat(), 0)
            card = MDCard(
                orientation="vertical",
                size_hint_y=None, height="56dp", padding="6dp",
                radius=[10], md_bg_color=(.96, .96, .96, 1), ripple_behavior=True,
            )
            card.add_widget(MDLabel(
                text=str(dcur.day),
                font_style="Caption",
                theme_text_color="Secondary",
                size_hint_y=None, height="14dp",
            ))
            card.add_widget(MDLabel(
                text=format_money(running),
                theme_text_color="Custom",
                text_color=(0, .6, 0, 1) if running >= 0 else (.8, 0, 0, 1),
                font_size="12sp",
            ))
            iso = dcur.isoformat()

            def _on_touch_up(instance, touch, _iso=iso):
                if instance.collide_point(*touch.pos):
                    self._selected_iso = _iso
                    self.refresh_today()
                return False
            card.bind(on_touch_up=_on_touch_up)
            grid.add_widget(card)
            dcur += timedelta(days=1)


if __name__ == "__main__":
    EasyBudgetApp().run()
