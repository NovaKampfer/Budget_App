# easybudget/widgets.py
#
# Reusable UI building blocks. Their look (colors, corners, sizes) is defined
# in widgets.kv; this file holds the behaviour.

from datetime import date, timedelta

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics.texture import Texture
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty, ColorProperty, ListProperty, NumericProperty, ObjectProperty,
    StringProperty,
)
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.textinput import TextInput
from kivymd.icon_definitions import md_icons


# ---------------------------------------------------------------------------
# Basic pieces
# ---------------------------------------------------------------------------
class Text(Label):
    """A themed label (see widgets.kv for defaults)."""


class Icon(Label):
    """A Material Design icon, e.g. Icon(icon="calendar")."""

    icon = StringProperty("")

    def on_icon(self, _inst, name):
        self.text = md_icons.get(name, "")


class IconButton(ButtonBehavior, Icon):
    """Round, 48dp touch target with a soft press highlight."""


class Card(BoxLayout):
    """Rounded surface with an optional soft shadow."""

    radius = NumericProperty(dp(20))
    bg = ColorProperty(None, allownone=True)
    shadow = BooleanProperty(True)


class TapCard(ButtonBehavior, Card):
    """A Card that can be tapped."""


class Pill(ButtonBehavior, BoxLayout):
    """Small rounded button with an icon and a label."""

    icon = StringProperty("")
    text = StringProperty("")
    fg = ColorProperty([1, 1, 1, 1])
    bg = ColorProperty([1, 1, 1, 0.18])


class PrimaryButton(ButtonBehavior, BoxLayout):
    text = StringProperty("")
    icon = StringProperty("")
    bg = ColorProperty(None, allownone=True)
    fg = ColorProperty(None, allownone=True)


class AutoText(Label):
    """A label exactly as wide as its text (not based on Text, whose
    text_size binding would fight with the width)."""


class TextButton(ButtonBehavior, Label):
    """Flat text button (dialogs, secondary actions)."""

    muted = BooleanProperty(False)


class Fab(ButtonBehavior, BoxLayout):
    icon = StringProperty("plus")
    angle = NumericProperty(0)


class Field(BoxLayout):
    """A labelled single-line text input on a rounded background."""

    label = StringProperty("")
    hint = StringProperty("")
    text = StringProperty("")
    icon = StringProperty("")
    focused = BooleanProperty(False)


class FieldInput(TextInput):
    pass


class PickerRow(ButtonBehavior, BoxLayout):
    """Tappable row showing a label + value (e.g. Date, Repeats)."""

    icon = StringProperty("")
    label = StringProperty("")
    value = StringProperty("")


# ---------------------------------------------------------------------------
# Gradient balance card
# ---------------------------------------------------------------------------
GRADIENT_SIZE = 32


def diagonal_gradient_bytes(top_left, bottom_right, size=GRADIENT_SIZE) -> bytes:
    buf = bytearray()
    last = size - 1
    for y in range(size):            # texture rows go bottom -> top
        for x in range(size):
            t = (x / last + (1 - y / last)) / 2
            for i in range(4):
                c = top_left[i] + (bottom_right[i] - top_left[i]) * t
                buf.append(int(max(0, min(1, c)) * 255))
    return bytes(buf)


class GradientCard(BoxLayout):
    color_a = ColorProperty([0, 0.5, 0.45, 1])
    color_b = ColorProperty([0, 0.3, 0.3, 1])
    radius = NumericProperty(dp(28))
    texture = ObjectProperty(None, allownone=True)

    def __init__(self, **kwargs):
        self._trigger = Clock.create_trigger(self._rebuild, -1)
        super().__init__(**kwargs)
        self._trigger()

    def on_color_a(self, *_):
        self._trigger()

    def on_color_b(self, *_):
        self._trigger()

    def _rebuild(self, *_):
        self._pixels = diagonal_gradient_bytes(self.color_a, self.color_b)
        tex = Texture.create(size=(GRADIENT_SIZE, GRADIENT_SIZE), colorfmt="rgba")
        tex.mag_filter = "linear"
        tex.min_filter = "linear"
        tex.wrap = "clamp_to_edge"
        self._upload(tex)
        # If the graphics context is ever rebuilt, upload the pixels again
        # (otherwise the card would come back blank).
        tex.add_reload_observer(self._upload)
        self.texture = tex

    def _upload(self, tex):
        tex.blit_buffer(self._pixels, colorfmt="rgba", bufferfmt="ubyte")


# ---------------------------------------------------------------------------
# Segmented control (Expense | Income, System | Light | Dark, ...)
# ---------------------------------------------------------------------------
class SegmentButton(ButtonBehavior, BoxLayout):
    key = StringProperty("")
    text = StringProperty("")
    icon = StringProperty("")
    active = BooleanProperty(False)
    active_color = ColorProperty([0, 0.5, 0.45, 1])


class Segmented(BoxLayout):
    """
    options: list of dicts {key, text, icon(optional), color(optional palette name)}
    value:   key of the selected option
    """

    options = ListProperty()
    value = StringProperty("")
    __events__ = ("on_select",)

    def on_options(self, *_):
        self.clear_widgets()
        app = App.get_running_app()
        for opt in self.options:
            btn = SegmentButton(key=opt["key"], text=opt["text"], icon=opt.get("icon", ""))
            color_name = opt.get("color", "primary")
            btn.active_color = getattr(app.pal, color_name)
            app.pal.bind(**{color_name: lambda _p, v, b=btn: setattr(b, "active_color", v)})
            btn.bind(on_release=self._clicked)
            self.add_widget(btn)
        self.on_value()

    def on_value(self, *_):
        for btn in self.children:
            btn.active = btn.key == self.value

    def _clicked(self, btn):
        if self.value != btn.key:
            self.value = btn.key
            self.dispatch("on_select", btn.key)

    def on_select(self, key):
        pass


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
class DayCell(BoxLayout):
    iso = StringProperty("")
    day = StringProperty("")
    amount = StringProperty("")
    status = StringProperty("ok")     # 'ok', 'low' (below warning) or 'neg'
    selected = BooleanProperty(False)
    is_today = BooleanProperty(False)
    in_month = BooleanProperty(True)


class MonthGrid(GridLayout):
    """
    7 x 6 grid of DayCells. Tap a day to select it; swipe left/right to change
    month. The owner fills the cells with `show()`.
    """

    __events__ = ("on_day", "on_swipe")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cells = [DayCell() for _ in range(42)]
        for cell in self.cells:
            self.add_widget(cell)

    def show(self, first_day: date, month: int, selected_iso: str,
             amounts=None, statuses=None):
        """first_day: the date in the top-left cell."""
        today = date.today().isoformat()
        amounts = amounts or {}
        statuses = statuses or {}
        d = first_day
        for cell in self.cells:
            iso = d.isoformat()
            cell.iso = iso
            cell.day = str(d.day)
            cell.in_month = d.month == month
            cell.is_today = iso == today
            cell.selected = iso == selected_iso
            cell.amount = amounts.get(iso, "")
            cell.status = statuses.get(iso, "ok")
            d += timedelta(days=1)

    # --- touch handling -------------------------------------------------
    def on_touch_down(self, touch):
        if self.collide_point(touch.ox, touch.oy) or self.collide_point(*touch.pos):
            touch.grab(self)
            touch.ud["monthgrid"] = True
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return super().on_touch_up(touch)
        touch.ungrab(self)
        dx = touch.x - touch.ox
        dy = touch.y - touch.oy
        if abs(dx) > dp(48) and abs(dx) > abs(dy) * 1.4:
            self.dispatch("on_swipe", -1 if dx > 0 else 1)
            return True
        if abs(dx) < dp(14) and abs(dy) < dp(14):
            for cell in self.cells:
                if cell.collide_point(*touch.pos):
                    self.dispatch("on_day", cell.iso)
                    break
        return True

    def on_day(self, iso):
        pass

    def on_swipe(self, direction):
        pass


# ---------------------------------------------------------------------------
# Number keypad (used instead of the system keyboard for amounts, so a
# decimal point is always available whatever keyboard the phone uses)
# ---------------------------------------------------------------------------
class KeyButton(ButtonBehavior, Label):
    key = StringProperty("")
    alt = BooleanProperty(False)


class Keypad(GridLayout):
    """alt=True uses the tinted key color (for keypads placed on a card)."""

    alt = BooleanProperty(False)
    __events__ = ("on_key",)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._clear_ev = None
        for key in ("1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "back"):
            btn = KeyButton(key=key, alt=self.alt)
            if key == "back":
                btn.text = f"[font=Icons]{md_icons['backspace-outline']}[/font]"
                btn.bind(on_press=self._back_pressed, on_release=self._back_released)
            else:
                btn.text = key
            btn.bind(on_release=self._pressed)
            self.add_widget(btn)

    def _pressed(self, btn):
        self.dispatch("on_key", btn.key)

    # long-press backspace clears everything
    def _back_pressed(self, _btn):
        self._clear_ev = Clock.schedule_once(lambda *_: self.dispatch("on_key", "clear"), 0.5)

    def _back_released(self, _btn):
        if self._clear_ev is not None:
            self._clear_ev.cancel()
            self._clear_ev = None

    def on_key(self, key):
        pass


def apply_key(current: str, key: str, max_int_digits: int = 9) -> str:
    """Return the amount string after pressing `key` on the keypad."""
    if key == "clear":
        return ""
    if key == "back":
        return current[:-1]
    if key == ".":
        if "." in current:
            return current
        return (current or "0") + "."
    if "." in current:
        if len(current.split(".", 1)[1]) >= 2:
            return current
        return current + key
    if current == "0":
        return key
    if len(current) >= max_int_digits:
        return current
    return current + key


def pretty_amount(raw: str) -> str:
    """'1234.5' -> '1,234.5' (keeps what the user typed after the point)."""
    if not raw:
        return "0"
    whole, dot, frac = raw.partition(".")
    whole = f"{int(whole):,}" if whole else "0"
    return whole + dot + frac


# ---------------------------------------------------------------------------
# Floating "+" button with a speed dial (Add / Add recurring)
# ---------------------------------------------------------------------------
class DialOption(ButtonBehavior, BoxLayout):
    icon = StringProperty("")
    text = StringProperty("")


class SpeedDial(FloatLayout):
    progress = NumericProperty(0)   # 0 = closed, 1 = open (animated)
    is_open = BooleanProperty(False)
    __events__ = ("on_add", "on_add_recurring")

    def toggle(self, *_):
        self.close() if self.is_open else self.open()

    def open(self):
        self.is_open = True
        Animation.cancel_all(self, "progress")
        Animation(progress=1, d=0.22, t="out_cubic").start(self)

    def close(self):
        self.is_open = False
        Animation.cancel_all(self, "progress")
        Animation(progress=0, d=0.18, t="out_quad").start(self)

    def choose(self, which):
        self.close()
        self.dispatch(which)

    def on_touch_down(self, touch):
        if not self.is_open and self.progress == 0:
            # Closed: only the round button itself reacts to touches.
            if self.ids.fab.collide_point(*touch.pos):
                return self.ids.fab.on_touch_down(touch)
            return False
        if super().on_touch_down(touch):
            return True
        self.close()
        return True

    def on_add(self):
        pass

    def on_add_recurring(self):
        pass


# ---------------------------------------------------------------------------
# Bottom sheet (actions, choices, date picker, amount entry, confirmations)
# ---------------------------------------------------------------------------
class SheetCard(BoxLayout):
    floating = BooleanProperty(False)


class BottomSheet(ModalView):
    """
    A panel that slides up from the bottom of the screen. Put content in
    `sheet.body` (a vertical BoxLayout).
    """

    title = StringProperty("")
    subtitle = StringProperty("")
    floating = BooleanProperty(False)   # True: a card near the top (for typing,
                                        # so the keyboard never covers it)

    def __init__(self, **kwargs):
        app = App.get_running_app()
        kwargs.setdefault("size_hint", (1, 1))
        kwargs.setdefault("background", "")
        kwargs.setdefault("background_color", (0, 0, 0, 0))
        kwargs.setdefault("overlay_color", app.pal.scrim)
        super().__init__(**kwargs)
        self.layer = FloatLayout()
        self.card = SheetCard(floating=self.floating)
        if self.floating:
            self.card.size_hint_x = None
            self.layer.bind(width=lambda _l, w: setattr(self.card, "width", w - dp(32)))
        self.layer.add_widget(self.card)
        self.add_widget(self.layer)
        self.body = self.card.ids.body
        self.card.ids.title.text = self.title
        self.card.ids.subtitle.text = self.subtitle
        self.bind(title=lambda *_: setattr(self.card.ids.title, "text", self.title),
                  subtitle=lambda *_: setattr(self.card.ids.subtitle, "text", self.subtitle))

    def open(self, *args, **kwargs):
        super().open(*args, **kwargs)
        self.card.y = -self.card.height - dp(40)
        if self.floating:
            self.card.opacity = 0
        Clock.schedule_once(self._slide_in, 0)

    def _floating_y(self):
        app = App.get_running_app()
        return self.layer.top - self.card.height - dp(72) - app.inset_top

    def _slide_in(self, *_):
        if self.floating:
            self.card.x = dp(16)
            self.card.y = self._floating_y() + dp(16)
            Animation(y=self._floating_y(), opacity=1, d=0.2, t="out_cubic").start(self.card)
            return
        self.card.y = -self.card.height
        Animation(y=0, d=0.24, t="out_cubic").start(self.card)

    def dismiss(self, *args, **kwargs):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        if self.floating:
            anim = Animation(opacity=0, y=self.card.y + dp(12), d=0.14, t="in_quad")
        else:
            anim = Animation(y=-self.card.height - dp(20), d=0.16, t="in_quad")
        anim.bind(on_complete=lambda *_: ModalView.dismiss(self, *args, **kwargs))
        anim.start(self.card)

    def on_touch_down(self, touch):
        if not self.card.collide_point(*touch.pos):
            if self.auto_dismiss:
                self.dismiss()
            return True
        return super().on_touch_down(touch)


class SheetRow(ButtonBehavior, BoxLayout):
    """One choice inside a bottom sheet."""

    icon = StringProperty("")
    text = StringProperty("")
    secondary = StringProperty("")
    checked = BooleanProperty(False)
    danger = BooleanProperty(False)


# ---------------------------------------------------------------------------
# Toast: a short message that fades in above the bottom of the screen
# ---------------------------------------------------------------------------
class Toast(BoxLayout):
    text = StringProperty("")
    icon = StringProperty("check-circle-outline")

    _current = None

    @classmethod
    def show(cls, text, icon="check-circle-outline", duration=2.2):
        if cls._current is not None and cls._current.parent:
            Window.remove_widget(cls._current)
        toast = cls(text=text, icon=icon, opacity=0)
        cls._current = toast
        Window.add_widget(toast)
        toast.y = dp(96)
        Animation(opacity=1, y=dp(112), d=0.18, t="out_quad").start(toast)

        def _hide(*_):
            anim = Animation(opacity=0, d=0.25)
            anim.bind(on_complete=lambda *_: toast.parent and Window.remove_widget(toast))
            anim.start(toast)

        Clock.schedule_once(_hide, duration)
