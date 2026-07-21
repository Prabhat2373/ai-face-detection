#!/usr/bin/env python3
"""
macOS first-run helper: copy application-bundled resources into the current user's
Application Support folder.

Purpose
-------
This script copies initial database, AI models, optional ffmpeg runtime,
public key, and any bundled license token from the application bundle's
Resources (or from a developer checkout) into:

    ~/Library/Application Support/FaceAgent

It is intended to be run by an installer or on first-run by the application
launcher. It is conservative: it will not overwrite an existing database
unless --force is specified.

Usage
-----
    # Auto-detect Resources and copy to default target
    python copy_initial_data_osx.py

    # Explicit install dir (e.g. inside .app/Contents/Resources)
    python copy_initial_data_osx.py --install-dir "/Applications/FaceAgent.app/Contents/Resources"

    # Force overwrite existing files
    python copy_initial_data_osx.py --force

    # Dry run
    python copy_initial_data_osx.py --dry-run --verbose

Notes
-----
- This script is macOS-specific (uses standard macOS path for Application Support).
- It makes best-effort attempts to set permissive user-only permissions on copied files.
- Logs are appended to: ~/Library/Logs/FaceAgent/copy_initial_data.log
"""

from __future__ import annotations

import argparse
import shutil
import stat
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# Defaults
APP_NAME = "FaceAgent"
DEFAULT_TARGET = Path.home() / "Library" / "Application Support" / APP_NAME
LOG_DIR = Path.home() / "Library" / "Logs" / APP_NAME
LOG_FILE = LOG_DIR / "copy_initial_data.log"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat()


def write_log(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(f"{now_iso()} {msg}\n")
    except Exception:
        # Fail silently on logging errors
        pass


def log(msg: str, *, level: str = "INFO", verbose: bool = False) -> None:
    line = f"[{level}] {msg}"
    if verbose or level in ("WARN", "ERROR"):
        print(line, file=sys.stderr if level in ("WARN", "ERROR") else sys.stdout)
    write_log(f"{level} {msg}")


def find_resource_root(explicit: Optional[Path] = None) -> Path:
    """
    Try to locate the directory that contains resources to copy.

    Strategy:
    - If explicit provided and exists, return it.
    - If running from inside a .app bundle, look for the nearest 'Resources'
      directory up the path chain (typical path: /.../FaceAgent.app/Contents/Resources).
    - Otherwise, look for likely development locations relative to this script:
      ../.. (project root), ../Resources, etc.
    - As a last resort, return the current working directory.
    """
    if explicit:
        p = Path(explicit).expanduser().resolve()
        if p.exists():
            return p

    # Detect Resources in bundle tree
    me = Path(__file__).resolve()
    for parent in me.parents:
        if parent.name == "Resources" and parent.exists():
            return parent

    # Common locations relative to this script (development checkout)
    candidates = [
        me.parents[2],  # project root (working_face_detection)
        me.parents[1] / "Resources",
        me.parents[2] / "Resources",
        me.parents[2] / "python_recognizer" / "data",
        me.parents[2],  # fallback to project root
        Path.cwd(),
    ]
    for c in candidates:
        try:
            if c and c.exists():
                # Heuristic: accept if contains python_recognizer or ui or licenses
                if (c / "python_recognizer").exists() or (c / "ui").exists() or (c / "licenses").exists() or (c / "insightface_models").exists():
                    return c
        except Exception:
            continue

    return Path.cwd()


def ensure_dir(path: Path, *, verbose: bool = False) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        try:
            # User-only permission for dir
            path.chmod(0o700)
        except Exception:
            pass
        if verbose:
            log(f"Ensured directory exists: {path}", verbose=verbose)
    except Exception as exc:
        log(f"Failed to ensure directory {path}: {exc}", level="ERROR", verbose=verbose)
        raise


def copy_file_if_missing(src: Path, dst: Path, force: bool = False, *, verbose: bool = False) -> bool:
    """
    Copy a file or small directory. Return True if copied, False if skipped.
    """
    if not src.exists():
        if verbose:
            log(f"Source not found, skipping: {src}", verbose=verbose)
        return False

    ensure_dir(dst.parent, verbose=verbose)

    if dst.exists():
        if force:
            try:
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
            except Exception as exc:
                log(f"Failed to remove existing {dst}: {exc}", level="WARN", verbose=verbose)
        else:
            if verbose:
                log(f"Destination exists, not overwriting: {dst}", verbose=verbose)
            return False

    try:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        try:
            if dst.is_file():
                dst.chmod(0o600)
        except Exception:
            pass
        if verbose:
            log(f"Copied {src} -> {dst}", verbose=verbose)
        return True
    except Exception as exc:
        log(f"Failed to copy {src} -> {dst}: {exc}", level="ERROR", verbose=verbose)
        return False


def copy_tree_if_missing(src: Path, dst: Path, force: bool = False, *, verbose: bool = False) -> bool:
    """
    Copy a directory tree if dst doesn't exist (or force==True).
    Returns True if copied, False if skipped.
    """
    if not src.exists() or not src.is_dir():
        if verbose:
            log(f"Source directory not found, skipping: {src}", verbose=verbose)
        return False

    if dst.exists():
        if not force:
            if verbose:
                log(f"Destination directory exists, skipping: {dst}", verbose=verbose)
            return False
        else:
            try:
                shutil.rmtree(dst)
            except Exception as exc:
                log(f"Failed to remove existing destination dir {dst}: {exc}", level="WARN", verbose=verbose)
                return False

    try:
        shutil.copytree(src, dst)
        # Relax permissions for user
        for p in dst.rglob("*"):
            try:
                if p.is_file():
                    p.chmod(0o600)
                elif p.is_dir():
                    p.chmod(0o700)
            except Exception:
                pass
        if verbose:
            log(f"Copied directory {src} -> {dst}", verbose=verbose)
        return True
    except Exception as exc:
        log(f"Failed to copy directory {src} -> {dst}: {exc}", level="ERROR", verbose=verbose)
        return False


def perform_copy(resource_root: Path, target: Path, force: bool = False, *, verbose: bool = False) -> int:
    """
    Copy expected resources from resource_root into the user-writable target.
    Returns 0 on success, non-zero on partial failures.
    """
    rc = 0
    log(f"Resource root: {resource_root}", verbose=verbose)
    log(f"Target user app data dir: {target}", verbose=verbose)

    ensure_dir(target, verbose=verbose)
    ensure_dir(target / "data", verbose=verbose)
    ensure_dir(target / "logs", verbose=verbose)
    ensure_dir(target / "snapshots", verbose=verbose)
    ensure_dir(target / "licenses", verbose=verbose)

    # Candidates for DB location
    db_candidates = [
        resource_root / "python_recognizer" / "data" / "app.db",
        resource_root / "data" / "app.db",
        resource_root / "app.db",
    ]
    db_copied = False
    for db_src in db_candidates:
        if db_src.exists():
            db_dst = target / "data" / "app.db"
            ok = copy_file_if_missing(db_src, db_dst, force=force, verbose=verbose)
            if ok:
                db_copied = True
            break
    if not db_copied:
        if verbose:
            log("No bundled database copied (not found or already exists).", verbose=verbose)

    # Snapshots (optional)
    snapshots_src = resource_root / "snapshots"
    if snapshots_src.exists():
        copy_tree_if_missing(snapshots_src, target / "snapshots", force=force, verbose=verbose)

    # Models (insightface_models)
    models_src = resource_root / "insightface_models"
    if models_src.exists():
        ok = copy_tree_if_missing(models_src, target / "insightface_models", force=force, verbose=verbose)
        if not ok:
            rc = max(rc, 2)
    else:
        if verbose:
            log("No insightface_models found in resources (skipping).", verbose=verbose)

    # ffmpeg runtime (optional)
    ffmpeg_src = resource_root / "ffmpeg_runtime"
    if ffmpeg_src.exists():
        ok = copy_tree_if_missing(ffmpeg_src, target / "ffmpeg_runtime", force=force, verbose=verbose)
        if not ok:
            rc = max(rc, 3)

    # Public key
    pub_src = resource_root / "licenses" / "public_key.pem"
    if pub_src.exists():
        copy_file_if_missing(pub_src, target / "licenses" / "public_key.pem", force=force, verbose=verbose)
    else:
        # maybe public_key.pem is at top-level resources
        alt_pub = resource_root / "public_key.pem"
        if alt_pub.exists():
            copy_file_if_missing(alt_pub, target / "licenses" / "public_key.pem", force=force, verbose=verbose)
        else:
            if verbose:
                log("No public_key.pem found in resources (skipping).", verbose=verbose)

    # Optional license token included in resources
    license_candidates = [
        resource_root / "license.key",
        resource_root / "license.token",
        resource_root / "licenses" / "license.key",
        resource_root / "licenses" / "license.token",
    ]
    for lic in license_candidates:
        if lic.exists():
            copy_file_if_missing(lic, target / "license.key", force=force, verbose=verbose)
            break

    # Ensure snapshots/logs directories exist
    ensure_dir(target / "snapshots", verbose=verbose)
    ensure_dir(target / "logs", verbose=verbose)

    # Best-effort: set user-owned permissions on target dir
    try:
        target.chmod(0o700)
    except Exception:
        pass

    log("Completed initial resource copy.", verbose=verbose)
    return rc


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Copy initial FaceAgent resources into user's Application Support (macOS)")
    p.add_argument("--install-dir", help="Explicit path to resources folder (e.g. /Applications/FaceAgent.app/Contents/Resources)")
    p.add_argument("--target-dir", help=f"Target directory (default: {DEFAULT_TARGET})")
    p.add_argument("--force", action="store_true", help="Overwrite existing files/directories")
    p.add_argument("--dry-run", action="store_true", help="Show actions but do not perform copy")
    p.add_argument("--verbose", action="store_true", help="Verbose output")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(list(argv or sys.argv[1:]))
    verbose = bool(args.verbose)
    dry_run = bool(args.dry_run)
    force = bool(args.force)

    try:
        resource_root = find_resource_root(Path(args.install_dir) if args.install_dir else None)
        target = Path(args.target_dir).expanduser().resolve() if args.target_dir else DEFAULT_TARGET

        log(f"Starting copy_initial_data_osx. resource_root={resource_root} target={target} force={force} dry_run={dry_run}", verbose=verbose)
        if dry_run:
            log("Dry-run mode: listing resources that would be copied:", verbose=verbose)
            candidates = [
                resource_root / "python_recognizer" / "data" / "app.db",
                resource_root / "insightface_models",
                resource_root / "ffmpeg_runtime",
                resource_root / "licenses" / "public_key.pem",
                resource_root / "license.key",
            ]
            for c in candidates:
                log(f"  - {c}", verbose=verbose)
            return 0

        # perform copy
        rc = perform_copy(resource_root, target, force=force, verbose=verbose)
        return rc
    except Exception as exc:
        log(f"Unhandled exception in copy_initial_data_osx: {exc}", level="ERROR", verbose=True)
        if verbose:
            traceback.print_exc()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
