[app]

# (str) Title of your application
title = EasyBudget

# (str) Package name / domain  ->  installed as org.novakampfer.easybudget
package.name = easybudget
package.domain = org.novakampfer

# (str) Source code where the main.py lives
source.dir = .

# (list) Source files to include
source.include_exts = py,png,kv

# (list) Folders to leave out of the APK
source.exclude_dirs = tests, bin, .buildozer, venv, .venv, __pycache__

# (str) Application versioning, read from easybudget/app.py
version.regex = __version__ = ['"](.*)['"]
version.filename = %(source.dir)s/easybudget/app.py

# (list) Application requirements
# No ads / analytics / network libraries - only the UI toolkit and SQLite.
requirements = python3,kivy==2.3.1,kivymd==1.2.0,sqlite3,pyjnius,android

# (str) Presplash and icons
presplash.filename = %(source.dir)s/assets/presplash.png
icon.filename = %(source.dir)s/assets/icon.png
icon.adaptive_foreground.filename = %(source.dir)s/assets/icon_fg.png
icon.adaptive_background.filename = %(source.dir)s/assets/icon_bg.png

# (list) Supported orientations
orientation = portrait

# (bool) Show the status bar
fullscreen = 0

#
# Android specific
#

# (str) Background color shown behind the presplash image
android.presplash_color = #00796B

# (list) Permissions: none. The app works fully offline and never
# touches the internet, contacts, storage or anything else.
#android.permissions =

# (int) Target Android API.
# 34 keeps the classic (non edge-to-edge) window on Android 15/16 phones,
# which Kivy's Android backend handles reliably. Google Play requires a
# higher target for new uploads; this setting is fine for installing the
# APK directly on your phone.
android.api = 34

# (int) Minimum API your APK / AAB will support (Android 7.0)
android.minapi = 24

# (list) The Android archs to build for.
# 64-bit ARM covers practically every phone made since ~2017.
# Don't add armeabi-v7a back for now: python-for-android re-creates its
# build virtualenv for the second arch on top of the first one, which breaks
# pip ("cannot import name 'capture_logging'") and fails the build.
android.archs = arm64-v8a

# (bool) Automatically accept the SDK license agreements (needed for CI)
android.accept_sdk_license = True

# (bool) Let Android back up the app's data (your budget) with your Google backup
android.allow_backup = True

# (str) The format used to package the app for release mode (aab or apk).
# CI builds in release mode so every APK is signed with the same key.
android.release_artifact = apk

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
