# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for FaceAgent

This spec bundles the launcher entrypoint and includes common data files
that should be available at runtime:

- python_recognizer/data/app.db
- licenses/public_key.pem
- insightface_models/ (if present)
- ffmpeg_runtime/ (if present)
- ui/ (resources used by the UI)

Place this spec at working_face_detection/packaging/faceagent.spec and run:
    pyinstaller packaging/faceagent.spec

Notes:
- The spec assumes the project root is one level up from this file.
- If a data file does not exist it will be skipped by PyInstaller at build time.
"""

import os
from pathlib import Path

# Import PyInstaller symbols (they are injected when PyInstaller runs this file).
# Keeping imports implicit here to avoid failures when static-analyzing the spec.
block_cipher = None

# Project layout
# PyInstaller injects SPECPATH which contains the folder containing the spec file
SPEC_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIR.parent

# Entry script (the launcher that orchestrates backend + UI + license checks)
ENTRY_SCRIPT = PROJECT_ROOT / "launcher.py"

# Collect a list of data tuples (source file/folder, destination inside bundle).
# PyInstaller accepts (src, dest) pairs where dest is a relative path inside the bundle.
datas = []

# Helper to add a file or directory if present (non-fatal if missing).
def _add_data_if_exists(src: Path, dest: str) -> None:
    try:
        if src.exists():
            # For directories, PyInstaller expects file tuples; include the directory path
            # as-is and let PyInstaller handle recursing when building. This is a common
            # pattern in spec files.
            if src.is_dir():
                # PyInstaller accepts directory entries as (src, dest) in many cases.
                datas.append((str(src), dest))
            else:
                datas.append((str(src), dest))
    except Exception:
        # Be permissive in the spec: missing files simply won't be bundled.
        pass

# Packaged database (if present)
_add_data_if_exists(PROJECT_ROOT / "python_recognizer" / "data" / "app.db", os.path.join("python_recognizer", "data"))

# Licensing public key
_add_data_if_exists(PROJECT_ROOT / "licenses" / "public_key.pem", "licenses")

# InsightFace model directory (if vendored)
_add_data_if_exists(PROJECT_ROOT / "insightface_models", "insightface_models")

# ffmpeg runtime (optional)
_add_data_if_exists(PROJECT_ROOT / "ffmpeg_runtime", "ffmpeg_runtime")

# UI resources
_add_data_if_exists(PROJECT_ROOT / "ui", "ui")

# Optional resources folder (icons, themes)
_add_data_if_exists(PROJECT_ROOT / "resources", "resources")

# Determine icon file if present (prefer .ico for Windows, .icns for macOS)
icon_file = None
ico = PROJECT_ROOT / "resources" / "icon.ico"
icns = PROJECT_ROOT / "resources" / "icon.icns"
if ico.exists():
    icon_file = str(ico)
elif icns.exists():
    icon_file = str(icns)

# Analysis
a = Analysis(
    [str(ENTRY_SCRIPT)],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FaceAgent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # GUI app: no console window
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FaceAgent",
)
