#!/usr/bin/env python3
"""
Build orchestration script to run PyInstaller for both the main FaceAgent app
and the standalone License Manager.

Place this file at:
  working_face_detection/packaging/build_all.py

Usage (from project root):
  python working_face_detection/packaging/build_all.py [--clean] [--onefile] [--dist DIR] [--work DIR]

This script:
- Optionally cleans previous build/dist artifacts
- Invokes PyInstaller for packaging/faceagent.spec
- Invokes PyInstaller for packaging/license_manager.spec

Notes:
- This script runs PyInstaller as a module via the current Python interpreter:
    python -m PyInstaller <spec>
  so ensure PyInstaller is installed in the active environment.
- It does not attempt platform-specific signing or installer creation; it only
  produces the PyInstaller bundles under `dist/`.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

# Project-relative paths
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent

FACEAGENT_SPEC = HERE / "faceagent.spec"
LICENSE_MANAGER_SPEC = HERE / "license_manager.spec"

DEFAULT_DIST = PROJECT_ROOT / "dist"
DEFAULT_BUILD = PROJECT_ROOT / "build"

PYINSTALLER_MODULE = [sys.executable, "-m", "PyInstaller"]


def run_cmd(cmd: List[str], env: Optional[dict] = None) -> int:
    print("RUN:", " ".join(cmd))
    return subprocess.call(cmd, env=env)


def clean_artifacts(dist: Path = DEFAULT_DIST, build: Path = DEFAULT_BUILD) -> None:
    """Remove typical PyInstaller artifacts (dist/ and build/)."""
    for p in (dist, build):
        if p.exists():
            print("Removing:", p)
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
            except Exception as exc:
                print("Warning: failed to remove", p, ":", exc)


def build_spec(spec: Path, onefile: bool = False, distpath: Optional[Path] = None, workpath: Optional[Path] = None, noconfirm: bool = True) -> int:
    """Build a given PyInstaller spec file."""
    if not spec.exists():
        print(f"Spec file not found: {spec}", file=sys.stderr)
        return 3

    cmd = PYINSTALLER_MODULE + [str(spec)]
    if onefile:
        cmd.append("--onefile")
    if noconfirm:
        cmd.append("--noconfirm")
    if distpath:
        cmd += ["--distpath", str(distpath)]
    if workpath:
        cmd += ["--workpath", str(workpath)]
    # Run the command
    rc = run_cmd(cmd)
    return rc


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build FaceAgent and LicenseManager with PyInstaller")
    p.add_argument("--clean", action="store_true", help="Remove previous dist/ and build/ artifacts before building")
    p.add_argument("--onefile", action="store_true", help="Build onefile executables (not recommended for GUI with data)")
    p.add_argument("--dist", type=Path, default=DEFAULT_DIST, help="Dist directory to place built artifacts")
    p.add_argument("--work", type=Path, default=DEFAULT_BUILD, help="Work directory for PyInstaller")
    p.add_argument("--no-confirm", action="store_true", help="Don't pass --noconfirm to PyInstaller")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))

    distpath = args.dist
    workpath = args.work
    onefile = bool(args.onefile)
    noconfirm = not bool(args.no_confirm)

    if args.clean:
        clean_artifacts(dist=distpath, build=workpath)

    # Ensure packaging specs exist
    if not FACEAGENT_SPEC.exists():
        print("Error: faceagent.spec not found at", FACEAGENT_SPEC, file=sys.stderr)
        return 2
    if not LICENSE_MANAGER_SPEC.exists():
        print("Error: license_manager.spec not found at", LICENSE_MANAGER_SPEC, file=sys.stderr)
        return 2

    # Build FaceAgent
    print("\n=== Building FaceAgent (main app) ===")
    rc = build_spec(FACEAGENT_SPEC, onefile=onefile, distpath=distpath, workpath=workpath, noconfirm=noconfirm)
    if rc != 0:
        print("PyInstaller failed for FaceAgent with exit code", rc, file=sys.stderr)
        return rc

    # Build License Manager
    print("\n=== Building License Manager (vendor app) ===")
    rc = build_spec(LICENSE_MANAGER_SPEC, onefile=onefile, distpath=distpath, workpath=workpath, noconfirm=noconfirm)
    if rc != 0:
        print("PyInstaller failed for License Manager with exit code", rc, file=sys.stderr)
        return rc

    print("\nBuilds complete. Artifacts placed in:", distpath)
    return 0


if __name__ == "__main__":
    sys.exit(main())
