# easybudget/android_utils.py
#
# Small wrappers around Android-only APIs. Every function is safe to call on a
# desktop computer too (it simply does nothing there), which lets you run and
# test the app with `python main.py` before building an APK.

import os

from kivy.utils import platform

IS_ANDROID = platform == "android"

# android.view.View flags (raw values so older Android versions don't choke)
_LIGHT_STATUS_BAR = 0x2000        # API 23+
_LIGHT_NAVIGATION_BAR = 0x10      # API 26+
_ANDROID_R_ID_CONTENT = 0x01020002


def _activity():
    from jnius import autoclass

    return autoclass("org.kivy.android.PythonActivity").mActivity


def system_prefers_dark() -> bool:
    """True when the phone's system-wide dark theme is switched on."""
    if not IS_ANDROID:
        return os.environ.get("EASYBUDGET_DARK") == "1"
    try:
        ui_mode = _activity().getResources().getConfiguration().uiMode
        return (ui_mode & 0x30) == 0x20   # UI_MODE_NIGHT_MASK / UI_MODE_NIGHT_YES
    except Exception:
        return False


def _to_android_color(rgba) -> int:
    r, g, b = (int(round(c * 255)) for c in rgba[:3])
    value = (0xFF << 24) | (r << 16) | (g << 8) | b
    return value - (1 << 32) if value >= (1 << 31) else value   # Java int is signed


def set_system_bars(rgba, dark_icons: bool) -> None:
    """Color the status bar / navigation bar to match the app background."""
    if not IS_ANDROID:
        return
    try:
        from android.runnable import run_on_ui_thread
    except Exception:
        return

    @run_on_ui_thread
    def _apply():
        try:
            window = _activity().getWindow()
            window.clearFlags(0x04000000)        # FLAG_TRANSLUCENT_STATUS
            window.addFlags(-0x80000000)         # FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS
            color = _to_android_color(rgba)
            window.setStatusBarColor(color)
            window.setNavigationBarColor(color)
            flags = (_LIGHT_STATUS_BAR | _LIGHT_NAVIGATION_BAR) if dark_icons else 0
            window.getDecorView().setSystemUiVisibility(flags)
        except Exception as exc:  # never crash the app over cosmetics
            print(f"[easybudget] could not color system bars: {exc}")

    _apply()


def system_bar_overlap():
    """
    (top, bottom) pixels of our window that sit *underneath* the status bar /
    navigation bar. Normally (0, 0); non-zero only on devices that force the
    app to draw edge-to-edge, so the UI can pad itself out of the way.
    """
    if not IS_ANDROID:
        return 0, 0
    try:
        from jnius import autoclass

        activity = _activity()
        decor = activity.getWindow().getDecorView()
        insets = decor.getRootWindowInsets()
        content = activity.findViewById(_ANDROID_R_ID_CONTENT)
        if insets is None or content is None:
            return 0, 0
        rect = autoclass("android.graphics.Rect")()
        content.getGlobalVisibleRect(rect)
        bar_top = insets.getSystemWindowInsetTop()
        bar_bottom = insets.getSystemWindowInsetBottom()
        top = max(0, bar_top - rect.top)
        bottom = max(0, bar_bottom - (decor.getHeight() - rect.bottom))
        return top, bottom
    except Exception as exc:
        print(f"[easybudget] could not read window insets: {exc}")
        return 0, 0

