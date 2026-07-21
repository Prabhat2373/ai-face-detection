#!/usr/bin/env python3
"""
PyInstaller build helper for FaceAgent.

This script is a convenience wrapper around PyInstaller that:
- Locates the project's PyInstaller spec file (packaging/faceagent.spec).
- Optionally cleans previous build artifacts.
- Invokes PyInstaller in a reproducible way with sensible defaults.
- Exposes extra arguments for customization.

Usage examples:
    # Basic build using the spec:
    python packaging/pyinstaller_build.py

    # Clean and rebuild:
    python packaging/pyinstaller_build.py --clean

    # Quick one-file build of the launcher (for testing):
    python packaging/pyinstaller_build.py --quick

Notes:
- Run this from the project root (working_face_detection) or it will attempt to
  resolve paths relative to the script location.
- Ensure PyInstaller is installed in the Python environment used to run this script.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# Project layout: this script is expected in working_face_detection/packaging/
SCRIPT_PATH = Path(__file__).resolve()
PROJECT_ROOT = SCRIPT_PATH.parents[1] if SCRIPT_PATH.parents and len(SCRIPT_PATH.parents) > 1 else Path.cwd()
PACKAGING_DIR = SCRIPT_PATH.parent
SPEC_DEFAULT = PACKAGING_DIR / "faceagent.spec"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"

PYINSTALLER_MODULE = "PyInstaller"  # invoked as: python -m PyInstaller


def find_python_executable() -> str:
    """
    Return the Python executable to be used to invoke PyInstaller.
    We prefer the current running interpreter.
    """
    return sys.executable


def run_subprocess(cmd: List[str], env: Optional[dict] = None) -> int:
    """
    Run a subprocess and forward stdout/stderr to the console.
    Returns the process return code.
    """
    print("Running:", " ".join(cmd))
    proc = subprocess.Popen(cmd, env=env)
    try:
        proc.wait()
    except KeyboardInterrupt:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
            proc.wait()
    return proc.returncode or 0


def remove_path(path: Path) -> None:
    """Remove a file or directory if it exists (safe)."""
    try:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            print(f"Removed: {path}")
    except Exception as exc:
        print(f"Warning: failed to remove {path}: {exc}", file=sys.stderr)


def clean_artifacts(dist: Path = DIST_DIR, build: Path = BUILD_DIR) -> None:
    """
    Remove common PyInstaller artifacts: dist/, build/.
    Does not touch source files.
    """
    print("Cleaning previous build artifacts...")
    remove_path(dist)
    remove_path(build)
    # Optionally remove __pycache__ directories under project root to avoid stale caches.
    for p in PROJECT_ROOT.rglob("__pycache__"):
        remove_path(p)


def build_with_spec(
    spec_path: Path,
    onefile: bool = False,
    clean_build: bool = False,
    noconfirm: bool = True,
    upx_dir: Optional[Path] = None,
    extra_args: Optional[List[str]] = None,
) -> int:
    """
    Build the application using a PyInstaller spec file.

    - spec_path: path to the .spec file
    - onefile: pass --onefile to PyInstaller (not typical with spec files)
    - clean_build: remove dist/ and build/ before building
    - noconfirm: pass --noconfirm to PyInstaller
    - upx_dir: optional path to UPX (if desired)
    - extra_args: additional raw arguments to forward to PyInstaller
    """
    if clean_build:
        clean_artifacts()

    python_exec = find_python_executable()
    cmd = [python_exec, "-m", "PyInstaller", str(spec_path)]

    if noconfirm:
        cmd.append("--noconfirm")
    if onefile:
        cmd.append("--onefile")
    if upx_dir:
        cmd += ["--upx-dir", str(upx_dir)]
    if extra_args:
        cmd += extra_args

    env = os.environ.copy()
    env["FACEAGENT_BUILDING"] = "1"

    return run_subprocess(cmd, env=env)


def build_onefile_entrypoint(script: Path, name: str = "FaceAgent", icon: Optional[Path] = None, extra_args: Optional[List[str]] = None) -> int:
    """
    Build a single-file executable using PyInstaller without a spec.
    Useful for quick iterative tests.
    """
    python_exec = find_python_executable()
    cmd = [python_exec, "-m", "PyInstaller", "--onefile", "--name", name, str(script)]
    if icon:
        cmd += ["--icon", str(icon)]
    if extra_args:
        cmd += extra_args

    env = os.environ.copy()
    env["FACEAGENT_BUILDING"] = "1"
    return run_subprocess(cmd, env=env)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="pyinstaller_build.py", description="Helper to build FaceAgent with PyInstaller")
    p.add_argument("--spec", type=Path, default=SPEC_DEFAULT, help="Path to PyInstaller spec file (default: packaging/faceagent.spec)")
    p.add_argument("--clean", action="store_true", help="Remove previous build artifacts (dist/, build/) before building")
    p.add_argument("--onefile", action="store_true", help="Build a single-file executable (may be slower and larger)")
    p.add_argument("--noconfirm", action="store_true", help="Pass --noconfirm to PyInstaller")
    p.add_argument("--upx-dir", type=Path, help="Path to UPX directory to enable executable compression")
    p.add_argument("--extra", help="Extra pyinstaller args (quoted string).", default="")
    p.add_argument("--quick", action="store_true", help="Quick build path: build a onefile from launcher.py (bypasses spec)")
    p.add_argument("--icon", type=Path, help="Optional icon file for direct onefile builds")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))

    spec_path: Path = args.spec
    if not spec_path.exists():
        print(f"Spec file not found at {spec_path}", file=sys.stderr)
        return 3

    extra_args: List[str] = []
    if args.extra:
        extra_args = args.extra.split()

    if args.quick:
        launcher = PROJECT_ROOT / "launcher.py"
        if not launcher.exists():
            print("Launcher entrypoint not found; cannot perform quick build.", file=sys.stderr)
            return 4
        return build_onefile_entrypoint(launcher, name="FaceAgent", icon=args.icon, extra_args=extra_args)

    rc = build_with_spec(
        spec_path=spec_path,
        onefile=args.onefile,
        clean_build=args.clean,
        noconfirm=args.noconfirm,
        upx_dir=args.upx_dir,
        extra_args=extra_args,
    )
    if rc != 0:
        print(f"PyInstaller failed with exit code {rc}", file=sys.stderr)
        return rc

    print("PyInstaller build completed.")
    print("\nPost-build next steps (manual):")
    print(" - On Windows: create an installer with Inno Setup using the files under dist/FaceAgent")
    print(" - On macOS: run the py2app recipe and create a DMG; sign & notarize if distributing")
    print(" - On Linux: assemble an AppDir and create an AppImage; create .desktop file and icons")
    print("\nEnsure your installer copies per-user data (DB, models, public key) into the user's application data folder on first run.")
    return 0


if __name__ == "__main__":
    rc = main()
    raise SystemExit(rc)
