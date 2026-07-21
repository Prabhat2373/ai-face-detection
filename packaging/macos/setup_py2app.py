#!/usr/bin/env python3
"""
py2app setup script for FaceAgent (macOS packaging).

Usage (run on macOS in the project root virtualenv that has py2app installed):
    python packaging/macos/setup_py2app.py py2app

This will produce a macOS .app bundle under `dist/FaceAgent.app`.

Notes:
- Run this on macOS only. Ensure `py2app` is installed in the build environment.
- This script bundles the launcher entrypoint (`launcher.py`) as the application
  entry and includes runtime resources (DB, public key, models, UI files) into
  the app Resources directory where possible.
- Code signing and notarization are out of scope for this script; see the
  `create_dmg.sh` helper for a post-build workflow that signs and packages DMG.
"""

from __future__ import annotations

import sys
from pathlib import Path
from setuptools import setup

# ---------------------------------------------------------------------------
# Project layout and metadata
# ---------------------------------------------------------------------------
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[2]  # working_face_detection/packaging/macos -> go up to project root

ENTRY_SCRIPT = PROJECT_ROOT / "launcher.py"

APP_NAME = "FaceAgent"
APP_VERSION = "1.0.0"
BUNDLE_ID = "com.faceagent.app"
ICON_FILE = PROJECT_ROOT / "resources" / "icon.icns"  # optional

# Resources to include in the .app bundle Resources/ folder.
# These paths are included if present in the project tree. They are copied as-is.
RESOURCES = [
    PROJECT_ROOT / "python_recognizer" / "data" / "app.db",
    PROJECT_ROOT / "licenses" / "public_key.pem",
    PROJECT_ROOT / "insightface_models",
    PROJECT_ROOT / "ffmpeg_runtime",
    PROJECT_ROOT / "ui",
    PROJECT_ROOT / "resources",
]

# Filter to only include existing resources as strings
resources_to_include = [str(p) for p in RESOURCES if p.exists()]

# ---------------------------------------------------------------------------
# py2app options
# ---------------------------------------------------------------------------
plist = {
    "CFBundleName": APP_NAME,
    "CFBundleDisplayName": APP_NAME,
    "CFBundleIdentifier": BUNDLE_ID,
    "CFBundleShortVersionString": APP_VERSION,
    "CFBundleVersion": APP_VERSION,
    "LSApplicationCategoryType": "public.app-category.utilities",
}

py2app_options = {
    "argv_emulation": False,
    "packages": [],      # add package names here if py2app misses them
    "includes": [],      # explicit module names if needed
    "resources": resources_to_include,
    "iconfile": str(ICON_FILE) if ICON_FILE.exists() else None,
    "plist": plist,
    "semi_standalone": False,
    "optimize": 1,
}

# ---------------------------------------------------------------------------
# Setup invocation
# ---------------------------------------------------------------------------
def _print_summary() -> None:
    print("py2app configuration summary")
    print("----------------------------")
    print("Project root:", PROJECT_ROOT)
    print("Entry script:", ENTRY_SCRIPT)
    print("App name:", APP_NAME)
    print("Bundle ID:", BUNDLE_ID)
    print("Icon file:", py2app_options.get("iconfile"))
    print("Resources included (if present):")
    for r in resources_to_include:
        print("  -", r)
    print()
    print("To build (macOS):")
    print("  python packaging/macos/setup_py2app.py py2app")
    print("After build: sign and notarize the generated .app and create a DMG for distribution.")

if __name__ == "__main__":
    _print_summary()
    # setuptools.setup will process command-line args (e.g. 'py2app')
    setup(
        app=[str(ENTRY_SCRIPT)],
        name=APP_NAME,
        version=APP_VERSION,
        options={"py2app": py2app_options},
        setup_requires=["py2app"],
    )
