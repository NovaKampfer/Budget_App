# easybudget/theme.py
#
# Light and dark color palettes.
#
# Every custom widget reads its colors from `app.pal.<name>` in the .kv files.
# Switching theme animates these properties to the other palette, and Kivy's
# property bindings repaint everything automatically.

from kivy.event import EventDispatcher
from kivy.properties import ColorProperty
from kivy.utils import get_color_from_hex


def hex_rgba(value: str, alpha: float = 1.0):
    r, g, b, _a = get_color_from_hex(value)
    return [r, g, b, alpha]


LIGHT = {
    "bg": "#F3F6F5",            # screen background
    "surface": "#FFFFFF",       # cards
    "surface_alt": "#E9EFED",   # chips, inputs, keypad keys
    "outline": "#DCE4E1",
    "text": "#16201E",
    "text_muted": "#66736F",
    "primary": "#00897B",       # teal, like the original EasyBudget
    "primary_soft": "#D5EEEA",  # selected day, soft highlights
    "primary_fg": "#FFFFFF",
    "positive": "#1E8E5A",
    "warning": "#DB7C00",
    "negative": "#E04848",
    "hero_top": "#12A594",      # balance card gradient
    "hero_bottom": "#00695F",
    "hero_fg": "#FFFFFF",
    "scrim": "#0B1413",
    "shadow": "#0B2A26",
}

DARK = {
    "bg": "#0C1211",
    "surface": "#162020",
    "surface_alt": "#203030",
    "outline": "#273735",
    "text": "#E3ECEA",
    "text_muted": "#92A39F",
    "primary": "#4FC3B4",
    "primary_soft": "#1B3B37",
    "primary_fg": "#00201C",
    "positive": "#5CCF8F",
    "warning": "#FFB74D",
    "negative": "#FF7A7A",
    "hero_top": "#137A6E",
    "hero_bottom": "#0A3F39",
    "hero_fg": "#F2FFFC",
    "scrim": "#000000",
    "shadow": "#000000",
}

# Some tokens are translucent; everything else is opaque.
ALPHAS = {
    "light": {"scrim": 0.38, "shadow": 0.10},
    "dark": {"scrim": 0.60, "shadow": 0.0},   # dark mode uses lighter surfaces instead
}


def palette_values(dark: bool) -> dict:
    src = DARK if dark else LIGHT
    alphas = ALPHAS["dark" if dark else "light"]
    return {name: hex_rgba(value, alphas.get(name, 1.0)) for name, value in src.items()}


class Palette(EventDispatcher):
    """Holds the current theme colors as animatable Kivy properties."""

    bg = ColorProperty()
    surface = ColorProperty()
    surface_alt = ColorProperty()
    outline = ColorProperty()
    text = ColorProperty()
    text_muted = ColorProperty()
    primary = ColorProperty()
    primary_soft = ColorProperty()
    primary_fg = ColorProperty()
    positive = ColorProperty()
    warning = ColorProperty()
    negative = ColorProperty()
    hero_top = ColorProperty()
    hero_bottom = ColorProperty()
    hero_fg = ColorProperty()
    scrim = ColorProperty()
    shadow = ColorProperty()

    def __init__(self, dark=False, **kwargs):
        super().__init__(**kwargs)
        self.apply(dark)

    def apply(self, dark: bool) -> None:
        for name, value in palette_values(dark).items():
            setattr(self, name, value)


def with_alpha(color, alpha: float):
    return [color[0], color[1], color[2], alpha]
