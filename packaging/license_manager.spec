# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for the standalone License Manager (vendor tool).

- Entry script: working_face_detection/license_manager/main.py
- Bundles the `license_manager` UI and reuses the project's `licenses` package.
- Includes optional assets from license_manager/assets.
- Produces a GUI executable (no console).

Build:
    pyinstaller packaging/license_manager.spec

Notes:
- Run this on the target platform (macOS for .app, Windows for .exe, Linux for AppImage).
- PyInstaller provides Analysis/PYZ/EXE/COLLECT symbols when it executes this spec.
"""

from pathlib import Path

# PyInstaller injects SPECPATH which contains the folder containing the spec file
spec_dir = Path(SPECPATH).resolve()
project_root = spec_dir.parent

# Entry script for the License Manager app
entry_script = project_root / "license_manager" / "main.py"

# Data files to include (assets such as icons)
datas = []
assets_dir = project_root / "license_manager" / "assets"
if assets_dir.exists():
    # include entire assets folder
    datas.append((str(assets_dir), "license_manager/assets"))

# Optionally include any other static files needed by the vendor app
# e.g. license templates, sample requests for offline testing (not required)
sample_dir = project_root / "license_manager" / "sample_requests"
if sample_dir.exists():
    datas.append((str(sample_dir), "license_manager/sample_requests"))

# Choose an icon if present (platform-specific icons recommended)
icon_file = None
ico = project_root / "resources" / "license_manager.ico"
icns = project_root / "resources" / "license_manager.icns"
if ico.exists():
    icon_file = str(ico)
elif icns.exists():
    icon_file = str(icns)

block_cipher = None

a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
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
    name="LicenseManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=icon_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    name="LicenseManager",
)
