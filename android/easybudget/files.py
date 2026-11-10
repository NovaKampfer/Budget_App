# easybudget/files.py
#
# Saving and opening backup files.
#
# On Android this uses the system file picker (the Storage Access Framework):
# you choose where to save the file (Downloads, Google Drive, ...) and which
# file to restore, so the app needs no storage permission at all.
# On a computer it simply uses the Downloads folder (or your home folder).

from pathlib import Path

from kivy.clock import mainthread

from .android_utils import IS_ANDROID

BACKUP_GLOB = "EasyBudget-backup*.json"
_REQUEST_SAVE = 7301
_REQUEST_OPEN = 7302
_RESULT_OK = -1          # android.app.Activity.RESULT_OK

_pending = {}            # request code -> callback waiting for the picker
_bound = False


# ---------------------------------------------------------------------------
# Android plumbing
# ---------------------------------------------------------------------------
def _activity():
    from jnius import autoclass

    return autoclass("org.kivy.android.PythonActivity").mActivity


def _on_activity_result(request_code, result_code, intent):
    # Called by Android on its UI thread when a file picker closes.
    handler = _pending.pop(request_code, None)
    if handler is None:
        return
    uri = intent.getData() if (result_code == _RESULT_OK and intent is not None) else None
    _deliver(handler, uri)


@mainthread
def _deliver(handler, uri):
    handler(uri)


def _start_picker(intent, request_code, handler):
    global _bound
    from android import activity

    if not _bound:
        activity.bind(on_activity_result=_on_activity_result)
        _bound = True
    _pending[request_code] = handler
    _activity().startActivityForResult(intent, request_code)


def _desktop_folder() -> Path:
    downloads = Path.home() / "Downloads"
    return downloads if downloads.is_dir() else Path.home()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def save_text(filename: str, text: str, on_done) -> None:
    """
    Let the user save `text` as a file. Calls on_done(saved, where, error):
    saved=False with error=None means the user cancelled.
    """
    if not IS_ANDROID:
        path = _desktop_folder() / filename
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:
            on_done(False, None, str(exc))
            return
        on_done(True, str(path), None)
        return

    from jnius import autoclass

    Intent = autoclass("android.content.Intent")
    String = autoclass("java.lang.String")
    intent = Intent(Intent.ACTION_CREATE_DOCUMENT)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    intent.setType("application/json")
    intent.putExtra(Intent.EXTRA_TITLE, String(filename))

    def handler(uri):
        if uri is None:
            on_done(False, None, None)
            return
        try:
            resolver = _activity().getContentResolver()
            try:
                stream = resolver.openOutputStream(uri, "wt")   # overwrite
            except Exception:
                stream = resolver.openOutputStream(uri)         # some providers lack "wt"
            writer = autoclass("java.io.OutputStreamWriter")(stream, "UTF-8")
            writer.write(text)
            writer.flush()
            writer.close()
        except Exception as exc:
            on_done(False, None, str(exc))
            return
        on_done(True, None, None)

    _start_picker(intent, _REQUEST_SAVE, handler)


def open_text(on_loaded) -> None:
    """
    Let the user pick a file to read. Calls on_loaded(text, name, error):
    text=None with error=None means the user cancelled.
    """
    if not IS_ANDROID:
        files = sorted(_desktop_folder().glob(BACKUP_GLOB), key=lambda p: p.stat().st_mtime)
        if not files:
            on_loaded(None, None, f"No {BACKUP_GLOB} file in {_desktop_folder()}")
            return
        on_loaded(files[-1].read_text(encoding="utf-8"), files[-1].name, None)
        return

    from jnius import autoclass

    Intent = autoclass("android.content.Intent")
    intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
    intent.addCategory(Intent.CATEGORY_OPENABLE)
    intent.setType("*/*")     # JSON files often show up as "unknown type"

    def handler(uri):
        if uri is None:
            on_loaded(None, None, None)
            return
        try:
            stream = _activity().getContentResolver().openInputStream(uri)
            reader = autoclass("java.io.BufferedReader")(
                autoclass("java.io.InputStreamReader")(stream, "UTF-8"))
            lines = []
            line = reader.readLine()
            while line is not None:
                lines.append(line)
                line = reader.readLine()
            reader.close()
        except Exception as exc:
            on_loaded(None, None, str(exc))
            return
        on_loaded("\n".join(lines), uri.getLastPathSegment(), None)

    _start_picker(intent, _REQUEST_OPEN, handler)
