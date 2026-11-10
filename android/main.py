# main.py
#
# EasyBudget for Android - entry point.
#
# Buildozer packages this folder into an APK and runs this file on the phone.
# You can also run it on a computer to try it out:   python main.py
# (it opens in a phone-sized window).

import os

from kivy.config import Config
from kivy.utils import platform

if platform not in ("android", "ios"):
    # Desktop preview: a phone-shaped window, and no red multitouch dots on right-click.
    Config.set("graphics", "width", os.environ.get("EASYBUDGET_WIDTH", "412"))
    Config.set("graphics", "height", os.environ.get("EASYBUDGET_HEIGHT", "880"))
    Config.set("input", "mouse", "mouse,multitouch_on_demand")

from easybudget.app import EasyBudgetApp  # noqa: E402  (must come after Config.set)

if __name__ == "__main__":
    EasyBudgetApp().run()
