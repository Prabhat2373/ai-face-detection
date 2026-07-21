#!/usr/bin/env python3
"""
Launcher for FaceAgent - start hidden backend (if needed), verify license, then launch UI.

Responsibilities:
- Ensure the launcher runs under the project's virtualenv Python (if .venv exists)
- Start backend process (packaged uvicorn) when appropriate
- If no license.key, launch UI in Activation Mode to collect Machine Request and import license
- Verify license.key cryptographically (licenses.manager)
- Pass activation/license state to UI via environment variables
- Launch the UI
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent


def ensure_venv_interpreter() -> None:
    """
    If a local virtual environment (.venv) exists next to the launcher, ensure we
    are running with that interpreter. If not, re-exec the current process using the
    venv's Python executable.

    This is a best-effort check that supports common venv layouts:
      - macOS / Linux: .venv/bin/python or .venv/bin/python3
      - Windows:       .venv\\Scripts\\python.exe or .venv\\Scripts\\python3.exe

    Improvements:
      - Use sys.prefix to detect whether we're already running inside the venv.
      - Use an environment flag (FACEAGENT_LAUNCHER_REEXEC=1) to avoid accidental re-exec loops.
      - Use os.execve so we can set the re-exec env flag for the new process.
    """
    try:
        venv_root = PROJECT_ROOT / ".venv"
    except Exception:
        return

    if not venv_root.exists():
        return

    # If we've already re-execed once, don't try again (prevents loops)
    if os.getenv("FACEAGENT_LAUNCHER_REEXEC", "") == "1":
        return

    # Candidate interpreter locations for common virtualenv layouts
    if os.name == "nt":
        candidates = [
            venv_root / "Scripts" / "python.exe",
            venv_root / "Scripts" / "python3.exe",
        ]
    else:
        candidates = [
            venv_root / "bin" / "python",
            venv_root / "bin" / "python3",
        ]

    venv_python = next((p for p in candidates if p.exists()), None)
    if venv_python is None:
        return

    try:
        # If sys.prefix indicates we're already using the venv, skip re-exec.
        sys_prefix = getattr(sys, "prefix", "")
        if str(sys_prefix).startswith(str(venv_root)):
            return

        current_exec = Path(sys.executable).resolve()
        venv_dir = venv_python.parent.resolve()

        # If current interpreter binary lives in the venv, skip re-exec.
        if str(current_exec).startswith(str(venv_dir)):
            return

        debug = os.getenv("FACEAGENT_LAUNCHER_DEBUG", "").lower() in {"1", "true", "yes", "on"}
        if debug:
            print(f"Launcher: re-execing with venv python: {venv_python} (current: {current_exec})")

        script_path = Path(__file__).resolve()
        # Prepare environment for the new process and mark that we've re-execed.
        new_env = os.environ.copy()
        new_env["FACEAGENT_LAUNCHER_REEXEC"] = "1"
        # Use execve so we can pass a modified environment (avoids repeating).
        os.execve(str(venv_python), [str(venv_python), str(script_path), *sys.argv[1:]], new_env)
    except Exception:
        # On any error, give up and continue with the current interpreter
        return


# Ensure we run under project's virtualenv Python (if available) as early as possible.
ensure_venv_interpreter()


# Backend helpers
try:
    from ui.backend_process import BackendProcess, is_backend_ready, writable_app_dir  # type: ignore
except Exception:
    BackendProcess = None  # type: ignore
    is_backend_ready = None  # type: ignore
    writable_app_dir = None  # type: ignore

# Licensing helpers
try:
    from licenses.manager import (
        get_machine_fingerprint,
        write_fingerprint_file,
        load_license,
        create_local_trial,
        LicenseInvalidError,
        LicenseExpiredError,
    )
except Exception:
    get_machine_fingerprint = None  # type: ignore
    write_fingerprint_file = None  # type: ignore
    load_license = None  # type: ignore
    create_local_trial = None  # type: ignore
    LicenseInvalidError = Exception  # type: ignore
    LicenseExpiredError = Exception  # type: ignore

DEFAULT_LICENSE_FILENAME = "license.key"
DEFAULT_TRIAL_DAYS = 14
BACKEND_STARTUP_TIMEOUT = float(os.getenv("FACEAGENT_BACKEND_STARTUP_TIMEOUT", "10.0"))
# Application version used in Machine Request; allow override via env at build/package time
APP_VERSION = os.getenv("FACEAGENT_VERSION", "1.0.0")


def wait_until_backend_ready(timeout: float = BACKEND_STARTUP_TIMEOUT) -> bool:
    if is_backend_ready is None:
        return False
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            if is_backend_ready(timeout=0.5):
                return True
        except Exception:
            pass
        time.sleep(min(0.25 + attempt * 0.05, 1.0))
    return False


def default_license_path() -> Path:
    try:
        if writable_app_dir is not None:
            return writable_app_dir() / DEFAULT_LICENSE_FILENAME
    except Exception:
        pass
    # fallback to a licenses folder in the project
    return PROJECT_ROOT / "licenses" / DEFAULT_LICENSE_FILENAME


def prepare_license(license_path: Path, allow_local_trial: bool) -> dict:
    """
    Verify or create a license file and return a simple info dict.
    Raises LicenseInvalidError or LicenseExpiredError on failure.
    """
    if load_license is None or create_local_trial is None:
        raise RuntimeError("License subsystem not available in this environment")

    if license_path.exists():
        lic = load_license(license_path, allow_local_trial=False)
        return {
            "license_type": lic.license_type,
            "issued_at": lic.issued_at.isoformat() if lic.issued_at else None,
            "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
            "is_local_trial": bool(lic.is_local_trial),
        }

    # no license file present
    if allow_local_trial:
        lic = create_local_trial(license_path, days=int(os.getenv("FACEAGENT_TRIAL_DAYS", str(DEFAULT_TRIAL_DAYS))))
        return {
            "license_type": lic.license_type,
            "issued_at": lic.issued_at.isoformat() if lic.issued_at else None,
            "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
            "is_local_trial": True,
        }

    raise LicenseInvalidError("No license file found and local trials are not allowed")


def verify_license(license_path: Path) -> dict:
    """
    Attempt to load and verify license at path. Returns dict info if valid.
    Raises LicenseInvalidError/LicenseExpiredError on failure.
    """
    if load_license is None:
        raise RuntimeError("License subsystem not available")
    lic = load_license(license_path, allow_local_trial=False)
    return {
        "license_type": lic.license_type,
        "issued_at": lic.issued_at.isoformat() if lic.issued_at else None,
        "expires_at": lic.expires_at.isoformat() if lic.expires_at else None,
        "is_local_trial": bool(lic.is_local_trial),
    }


def launch_ui_activation(ui_script: Path, env: dict[str, str]) -> int:
    """Launch the UI in Activation Mode (subprocess) and return the exit code."""
    cmd = [sys.executable, str(ui_script), "--activation", "--no-auto-backend"]
    proc = subprocess.Popen(cmd, env=env)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        try:
            proc.terminate()
            return proc.wait(timeout=5)
        except Exception:
            proc.kill()
            return proc.wait()


def launch_ui_normal(ui_script: Path, env: dict[str, str]) -> int:
    """Launch main UI (subprocess) and return exit code."""
    cmd = [sys.executable, str(ui_script), "--no-auto-backend"]
    proc = subprocess.Popen(cmd, env=env)
    try:
        return proc.wait()
    except KeyboardInterrupt:
        try:
            proc.terminate()
            return proc.wait(timeout=5)
        except Exception:
            proc.kill()
            return proc.wait()


def set_license_env(env: dict, info: dict) -> None:
    """Populate license info into the environment for UI/backend processes."""
    env.setdefault("FACEAGENT_LICENSE_TYPE", str(info.get("license_type", "")))
    if info.get("issued_at"):
        env.setdefault("FACEAGENT_LICENSE_ISSUED_AT", info.get("issued_at"))
    if info.get("expires_at"):
        env.setdefault("FACEAGENT_LICENSE_EXPIRES_AT", info.get("expires_at"))
    env.setdefault("FACEAGENT_LICENSE_IS_LOCAL_TRIAL", str(bool(info.get("is_local_trial", False))))


def main(argv: Optional[list[str]] = None) -> int:
    argv = list(argv or sys.argv[1:])
    p = argparse.ArgumentParser(description="FaceAgent launcher (activation + normal startup)")
    p.add_argument("--no-backend", action="store_true")
    p.add_argument("--license-path")
    p.add_argument("--generate-fingerprint")
    p.add_argument("--auto-create-trial", action="store_true")
    p.add_argument("--trial-days", type=int, default=DEFAULT_TRIAL_DAYS)
    p.add_argument("--no-launch-ui", action="store_true")
    p.add_argument("--no-auto-start-backend", action="store_true")
    p.add_argument("--no-backend-check", action="store_true")
    p.add_argument("--no-backend-health-check", action="store_true")
    p.add_argument("--activation-only", action="store_true")
    p.add_argument("--activation", action="store_true")
    p.add_argument("--no-ui", action="store_true")
    p.add_argument("--no-auto-backend", action="store_true")
    args = p.parse_args(argv)

    # Determine license path
    license_path = Path(args.license_path) if args.license_path else default_license_path()

    # Decide whether to auto-start the backend. We start backend first so activation
    # UI (which runs in a subprocess) can run while backend is available.
    no_start_backend = args.no_backend or args.no_auto_start_backend or os.getenv("FACEAGENT_LAUNCHER_NO_BACKEND", "").lower() in {"1", "true", "yes", "on"}

    backend_proc = None
    started_backend = False
    if not no_start_backend:
        if is_backend_ready is None or BackendProcess is None:
            print("Backend helper not available: cannot auto-start backend.", file=sys.stderr)
            return 11
        # If an external backend is already healthy, do not start one
        try:
            if is_backend_ready(timeout=0.5):
                print("Detected external backend; not starting packaged backend.")
            else:
                print("Starting packaged backend (hidden)...")
                backend_proc = BackendProcess()
                backend_proc.start()
                started_backend = True
                print("Waiting for backend to become healthy...")
                ok = wait_until_backend_ready()
                if not ok:
                    print("Warning: backend did not become healthy within timeout. You may check backend logs if there are issues.", file=sys.stderr)
                else:
                    print("Backend is healthy.")
        except Exception as exc:
            print("Failed to start backend:", exc, file=sys.stderr)
            return 12
    else:
        print("Launcher configured not to start backend (connect to external backend).")

    # Activation loop:
    # If a valid license exists, prepare license_info. If not, launch the UI in
    # Activation Mode so the user can create a Machine Request and import license.key.
    license_info = None
    if load_license is None:
        print("License subsystem not available: cannot verify licenses. Ensure dependencies are installed.", file=sys.stderr)
        # Stop backend if we started it
        if started_backend and backend_proc is not None:
            try:
                backend_proc.stop()
            except Exception:
                pass
        return 4

    # Loop: check license, if missing/invalid then run Activation UI (subprocess) and re-check.
    while True:
        try:
            if license_path.exists():
                # Attempt to verify the installed license (no local trial allowed here)
                license_info = prepare_license(license_path, allow_local_trial=False)
                print(f"Loaded license from {license_path}: type={license_info.get('license_type')} expires={license_info.get('expires_at')}")
                break  # valid license found
            else:
                # No license present -> fall through to activation
                print(f"No license found at {license_path}; entering Activation Mode.")
        except LicenseExpiredError as exc:
            print("License has expired:", exc, file=sys.stderr)
            # Treat as missing and enter Activation Mode so user can import a new license
        except LicenseInvalidError as exc:
            print("License invalid:", exc, file=sys.stderr)
            # Treat as missing and enter Activation Mode
        except Exception as exc:
            print("Unexpected license error:", exc, file=sys.stderr)
            # Treat as missing and enter Activation Mode

        # Launch Activation UI as a subprocess. The UI will copy an imported license
        # into the per-user location. We pass FACEAGENT_ACTIVATION=1 so the UI knows its mode.
        ui_script = PROJECT_ROOT / "ui" / "app.py"
        if getattr(sys, "frozen", False):
            # When frozen launcher runs, starting the same executable with --activation
            cmd = [sys.executable, "--activation"]  # frozen exe handles activation flag
        else:
            cmd = [sys.executable, str(ui_script), "--activation"]

        env_act = os.environ.copy()
        env_act.setdefault("FACEAGENT_ACTIVATION", "1")
        # Ensure UI will not try to auto-start backend; launcher manages backend
        env_act.setdefault("FACEAGENT_NO_AUTO_START_BACKEND", "1")
        # Provide app version so Activation UI embeds app_version in Machine Request JSON
        env_act.setdefault("FACEAGENT_VERSION", APP_VERSION)

        print("Launching Activation UI...")
        try:
            proc = subprocess.Popen(cmd, env=env_act)
            rc = proc.wait()
        except Exception as exc:
            print("Failed to launch Activation UI:", exc, file=sys.stderr)
            # Stop backend if we started it
            if started_backend and backend_proc is not None:
                try:
                    backend_proc.stop()
                except Exception:
                    pass
            return 13

        # Activation UI exit codes:
        # 0 -> user completed activation steps (may have imported license.key)
        # 2 -> user cancelled activation -> we should abort and exit
        if rc == 2:
            print("User cancelled activation; exiting.", file=sys.stderr)
            if started_backend and backend_proc is not None:
                try:
                    backend_proc.stop()
                except Exception:
                    pass
            return 2

        # Otherwise loop back and re-check license_path; if a valid license was installed
        # by the Activation UI, prepare_license() will succeed and break the loop.
        print("Activation UI exited; re-checking for installed license...")
        # Continue loop to attempt load_license again

    # Set license info environment for UI/backend
    env = os.environ.copy()
    try:
        set_license_env(env, license_info or {})
    except Exception:
        pass

    # Backend was already started earlier according to launcher policy.
    # Do not attempt to start the backend again here to avoid duplicate attempts.
    # Proceed directly to launching the UI. If the backend was intentionally
    # not auto-started, the UI will operate against an external backend.
    print("Proceeding to UI launch with license state.")

    # Optionally skip UI launch
    if getattr(args, "no_launch_ui", False):
        print("License validated. Skipping UI launch as requested (--no-launch-ui).")
        # Stop backend if we started it
        if started_backend and backend_proc is not None:
            try:
                backend_proc.stop()
            except Exception:
                pass
        return 0

    # Launch the UI. Prefer subprocess running ui/app.py
    ui_script = PROJECT_ROOT / "ui" / "app.py"
    exit_code = 0
    try:
        if getattr(sys, "frozen", False):
            # When frozen, try to launch UI by executing the same frozen binary without args
            try:
                print("Launching UI (frozen bundle) as new process...")
                cmd = [sys.executable]
                env["FACEAGENT_NO_AUTO_START_BACKEND"] = "1"
                proc = subprocess.Popen(cmd, env=env)
                exit_code = proc.wait()
            except Exception as exc:
                print("Failed to launch UI from frozen bundle:", exc, file=sys.stderr)
                exit_code = 3
        else:
            if not ui_script.exists():
                # If UI script isn't found in source layout, bail out gracefully.
                print("UI script not found; cannot launch UI.")
                exit_code = 1
            else:
                env["FACEAGENT_NO_AUTO_START_BACKEND"] = "1"
                exit_code = launch_ui_normal(ui_script, env)
    finally:
        # Stop backend if we started it
        if started_backend and backend_proc is not None:
            try:
                backend_proc.stop()
            except Exception:
                pass

    return int(exit_code or 0)


if __name__ == "__main__":
    raise SystemExit(main())
