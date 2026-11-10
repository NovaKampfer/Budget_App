# easybudget/widgets.py
#
# Reusable UI building blocks. Their look (colors, corners, sizes) is defined
# in widgets.kv; this file holds the behaviour.

from datetime import date, timedelta

from kivy.animation import Animation
from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import PopMatrix, PushMatrix, Translate
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
from kivy.uix.scrollview import ScrollView
from kivy.uix.stencilview import StencilView
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
    7 x 6 grid of DayCells (display only). Fill it with `show()`.

    The selected-day and today highlights are drawn once by the grid (see
    widgets.kv) instead of by every cell: invisible per-cell shapes would
    still cost a GPU draw call each, every frame.
    """

    sel_rect = ListProperty([0, 0, dp(40), dp(40)])
    sel_visible = BooleanProperty(False)
    today_rect = ListProperty([0, 0, dp(40), dp(40)])
    today_visible = BooleanProperty(False)

    def __init__(self, **kwargs):
        self._marks = (None, None)
        super().__init__(**kwargs)
        self.cells = [DayCell() for _ in range(42)]
        for cell in self.cells:
            self.add_widget(cell)

    def do_layout(self, *args):
        super().do_layout(*args)
        self._update_marks()

    def _update_marks(self):
        selected_iso, today_iso = self._marks
        self.sel_visible = self.today_visible = False
        for cell in self.cells:
            rect = [cell.x, cell.y, cell.width, cell.height]
            if cell.iso == selected_iso:
                self.sel_rect, self.sel_visible = rect, True
            elif cell.iso == today_iso:
                self.today_rect, self.today_visible = rect, True

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
        self._marks = (selected_iso, today)
        self._update_marks()

    def cell_at(self, x, y):
        for cell in self.cells:
            if cell.collide_point(x, y):
                return cell
        return None


class MonthPager(StencilView):
    """
    A month calendar you can swipe like a carousel: the grid follows your
    finger, the neighbouring month slides in beside it, and on release it
    glides to that month (or springs back if the swipe was too short).

    `provider(delta)` must return MonthGrid.show() arguments for the visible
    month + delta (delta = -1 previous, 0 current, +1 next).
    Events: on_day(iso) when a day is tapped, on_page(delta) after a slide.

    To keep month changes instant:
    - the previous and next months are drawn ahead of time (in idle frames),
      so a swipe never waits for 42 cells to be filled in;
    - after a slide the grids are rotated, not re-filled;
    - a new tap or swipe finishes a running slide at once instead of being
      ignored until it ends.
    """

    offset = NumericProperty(0)          # horizontal drag offset in pixels
    row_height = NumericProperty(dp(54))
    __events__ = ("on_day", "on_page")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.provider = None
        self.grids = {d: MonthGrid(size_hint=(None, None)) for d in (-1, 0, 1)}
        self._fresh = {-1: False, 1: False}   # neighbour grids up to date?
        self._showing = 0                     # neighbour currently attached (0 = none)
        self._glide = None                    # (animation, finish callback) while sliding
        # Grids are moved with a Translate instruction instead of changing
        # their position, so the cells are never re-laid out while sliding.
        self._shift = {}
        for grid in self.grids.values():
            grid.canvas.before.insert(0, PushMatrix())
            self._shift[grid] = Translate()
            grid.canvas.before.insert(1, self._shift[grid])
            grid.canvas.after.add(PopMatrix())
        self.add_widget(self.grids[0])       # neighbours are only attached while sliding
        self._prefetch_trigger = Clock.create_trigger(self._prefetch, 0.05)
        self.bind(pos=self._layout, size=self._layout, row_height=self._layout,
                  offset=self._move)
        self._layout()

    @property
    def current(self):
        return self.grids[0]

    # --- drawing ------------------------------------------------------------
    def show(self, **data):
        """Show the visible month; neighbours are refreshed in a later frame."""
        if self._glide is not None:
            # An explicit jump (e.g. to today) wins over a slide still running.
            anim, _finish = self._glide
            self._glide = None
            anim.cancel(self)
            self.offset = 0
            self._show_neighbor(0)
        self.grids[0].show(**data)
        self._fresh = {-1: False, 1: False}
        self._prefetch_trigger()

    def _prefetch(self, *_):
        if self._glide is not None or not self.provider:
            self._prefetch_trigger()          # busy: try again shortly
            return
        for d in (-1, 1):
            if not self._fresh[d] and d != self._showing:
                self.grids[d].show(**self.provider(d))
                self._fresh[d] = True

    def _layout(self, *_):
        for grid in self.grids.values():
            grid.row_default_height = self.row_height
            grid.size = (self.width, self.row_height * 6)
            grid.pos = self.pos
        self._move()

    def _move(self, *_):
        self._shift[self.grids[0]].x = self.offset
        for d in (-1, 1):
            self._shift[self.grids[d]].x = self.offset + d * self.width

    def _show_neighbor(self, delta):
        """Attach the grid for month + delta (or detach it when delta == 0)."""
        if delta == self._showing:
            return
        if self._showing:
            self.remove_widget(self.grids[self._showing])
        if delta:
            if not self._fresh[delta] and self.provider:
                self.grids[delta].show(**self.provider(delta))
                self._fresh[delta] = True
            self.add_widget(self.grids[delta], index=len(self.children))
        self._showing = delta

    # --- paging ---------------------------------------------------------------
    def page(self, delta):
        """Slide to the previous (-1) / next (+1) month (arrow buttons)."""
        self.finish_slide()
        self._show_neighbor(delta)
        self._glide_to(delta)

    def finish_slide(self):
        """Jump to the end of a running slide right away."""
        if self._glide is not None:
            anim, finish = self._glide
            anim.cancel(self)
            finish()

    def _glide_to(self, delta):
        """Animate to the neighbouring month (delta != 0) or back (delta == 0)."""
        target = -delta * self.width
        distance = abs(target - self.offset) / max(self.width, 1)
        anim = Animation(offset=target, d=0.06 + 0.16 * distance, t="out_cubic")

        def finish(*_):
            if self._glide is None or self._glide[0] is not anim:
                return
            self._glide = None
            if delta:
                # Rotate: the grid that slid in (already attached) becomes the
                # current month; the old current month is detached and becomes
                # the neighbour on the other side.
                g = self.grids
                outgoing, incoming = g[0], g[delta]
                self.remove_widget(outgoing)
                g[-delta], g[0], g[delta] = outgoing, incoming, g[-delta]
                self._showing = 0
                self._fresh = {-delta: False, delta: False}
            else:
                self._show_neighbor(0)
            self.offset = 0
            self._move()
            if delta:
                self.dispatch("on_page", delta)
            self._prefetch_trigger()

        anim.bind(on_complete=finish)
        self._glide = (anim, finish)
        anim.start(self)

    # --- touch handling -------------------------------------------------------
    def on_touch_down(self, touch):
        if not self.collide_point(touch.ox, touch.oy):
            return False
        self.finish_slide()
        touch.grab(self)
        touch.ud[self] = {"dragging": False, "samples": [(touch.time_update, touch.x)]}
        self._drag(touch)
        return True

    def on_touch_move(self, touch):
        if touch.grab_current is not self:
            return False
        self._drag(touch)
        return True

    def _drag(self, touch):
        state = touch.ud.get(self)
        if state is None:
            return
        dx = touch.x - touch.ox
        dy = touch.y - touch.oy
        if not state["dragging"]:
            if abs(dx) < dp(6) or abs(dx) < abs(dy):
                return
            state["dragging"] = True
        state["samples"] = (state["samples"] + [(touch.time_update, touch.x)])[-6:]
        self._show_neighbor(1 if dx < 0 else -1)
        self.offset = max(-self.width, min(self.width, dx))

    def on_touch_up(self, touch):
        if touch.grab_current is not self:
            return False
        touch.ungrab(self)
        state = touch.ud.get(self)
        if state is None:
            return True
        if state["dragging"]:
            self._glide_to(self._release_target(state["samples"]))
        elif abs(touch.x - touch.ox) < dp(14) and abs(touch.y - touch.oy) < dp(14):
            cell = self.current.cell_at(*touch.pos)
            if cell is not None:
                self.dispatch("on_day", cell.iso)
        return True

    def _release_target(self, samples):
        """Month to glide to after letting go: +1 next, -1 previous, 0 stay.
        Same rule as Android's ViewPager: a quick flick (>= 400dp/s over at
        least 25dp) turns the page, otherwise the drag must pass 35%."""
        t_end, x_end = samples[-1]
        recent = [s for s in samples if t_end - s[0] <= 0.1] or samples[-2:]
        t_start, x_start = recent[0] if len(recent) > 1 else samples[max(0, len(samples) - 2)]
        velocity = (x_end - x_start) / (t_end - t_start) if t_end - t_start > 0.004 else 0
        if abs(self.offset) >= dp(25) and abs(velocity) >= dp(400) \
                and (velocity < 0) == (self.offset < 0):
            return 1 if velocity < 0 else -1
        if abs(self.offset) > self.width * 0.35:
            return 1 if self.offset < 0 else -1
        return 0

    def on_day(self, iso):
        pass

    def on_page(self, delta):
        pass


class DirectionLockScrollView(ScrollView):
    """
    A vertical ScrollView that lets sideways swipes which start on
    `swipe_target` (the calendar) go to it instead of scrolling the page.

    Kivy's ScrollView starts scrolling as soon as a finger drifts ~20px
    vertically, which almost every real sideways swipe does. Here a touch on
    the calendar first waits until it has moved `lock_distance`, then is
    locked to whichever direction it mostly moved in.
    """

    swipe_target = ObjectProperty(None, allownone=True)
    lock_distance = NumericProperty(dp(10))

    # --- keep the page still when its height changes ---------------------------
    # Kivy remembers the scroll position as a fraction of the page, so when the
    # page gets taller or shorter (e.g. a day with more or fewer transactions)
    # everything visibly jumps. Instead we keep the distance from the top.
    def __init__(self, **kwargs):
        self._top_offset = 0.0
        self._keeping = False
        super().__init__(**kwargs)
        self.fbind("scroll_y", self._remember_top)

    def add_widget(self, widget, *args, **kwargs):
        super().add_widget(widget, *args, **kwargs)
        widget.fbind("height", self._keep_top)

    def remove_widget(self, widget, *args, **kwargs):
        widget.funbind("height", self._keep_top)
        super().remove_widget(widget, *args, **kwargs)

    def _scroll_range(self):
        content = self._viewport
        return max(0.0, content.height - self.height) if content else 0.0

    def _remember_top(self, *_):
        if not self._keeping:
            self._top_offset = max(0.0, (1.0 - self.scroll_y) * self._scroll_range())

    def _keep_top(self, *_):
        scroll_range = self._scroll_range()
        self._keeping = True
        try:
            if scroll_range > 0:
                self.scroll_y = 1.0 - min(self._top_offset, scroll_range) / scroll_range
            else:
                self.scroll_y = 1.0
        finally:
            self._keeping = False

    def on_scroll_start(self, touch, check_children=True):
        handled = super().on_scroll_start(touch, check_children)
        ud = touch.ud.get(self._get_uid())
        if handled and ud is not None and self._starts_on_target(touch):
            ud["eb_lock"] = "undecided"
        return handled

    def _starts_on_target(self, touch):
        target = self.swipe_target
        if target is None or target.parent is None or self.parent is None:
            return False
        wx, wy = self.parent.to_window(touch.ox, touch.oy)
        x0, y0 = target.to_window(target.x, target.y)
        x1, y1 = target.to_window(target.right, target.top)
        return x0 <= wx <= x1 and y0 <= wy <= y1

    def on_scroll_move(self, touch):
        ud = touch.ud.get(self._get_uid())
        lock = ud.get("eb_lock") if ud is not None else None
        if lock and ud["mode"] == "unknown":
            if lock == "handing_over":
                return True                     # waiting for Kivy to pass the touch on
            dx = abs(touch.x - touch.ox)
            dy = abs(touch.y - touch.oy)
            if max(dx, dy) < self.lock_distance:
                return True                     # direction not clear yet
            if dx > dy:
                # Sideways: give the touch to the calendar. Kivy's own handoff
                # runs on the next frame, outside this event, where the touch
                # is in window coordinates as it expects.
                ud["eb_lock"] = "handing_over"
                Clock.schedule_once(self._change_touch_mode, 0)
                return True
            ud["eb_lock"] = None                # vertical: scroll right away
            ud["mode"] = "scroll"
        return super().on_scroll_move(touch)


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
    slide = NumericProperty(0)      # vertical offset while sliding in / out

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Slide with a Translate instead of moving the card, so its rows are
        # not re-laid out on every animation frame.
        self.canvas.before.insert(0, PushMatrix())
        self._shift = Translate()
        self.canvas.before.insert(1, self._shift)
        self.canvas.after.add(PopMatrix())
        self.bind(slide=lambda _c, v: setattr(self._shift, "y", v))


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
        self.card.slide = -Window.height * 2     # off screen until laid out
        if self.floating:
            self.card.opacity = 0
        Clock.schedule_once(self._slide_in, 0)

    def _floating_y(self):
        app = App.get_running_app()
        return self.layer.top - self.card.height - dp(72) - app.inset_top

    def _slide_in(self, *_):
        if self.floating:
            self.card.x = dp(16)
            self.card.y = self._floating_y()
            self.card.slide = dp(16)
            Animation(slide=0, opacity=1, d=0.2, t="out_cubic").start(self.card)
            return
        self.card.y = 0
        self.card.slide = -self.card.height
        Animation(slide=0, d=0.24, t="out_cubic").start(self.card)

    def dismiss(self, *args, **kwargs):
        if getattr(self, "_closing", False):
            return
        self._closing = True
        Animation.cancel_all(self.card)
        if self.floating:
            anim = Animation(opacity=0, slide=dp(12), d=0.14, t="in_quad")
        else:
            anim = Animation(slide=-self.card.height - dp(20), d=0.16, t="in_quad")
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
