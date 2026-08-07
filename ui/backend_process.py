"""Launch and manage the local backend for the desktop app."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib import request


BACKEND_URL = os.getenv("FACEAGENT_BACKEND_URL", "http://127.0.0.1:51873").rstrip("/")
BACKEND_HOST = os.getenv("FACEAGENT_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = os.getenv("FACEAGENT_BACKEND_PORT", "51873")


def is_backend_ready(timeout: float = 0.5) -> bool:
    try:
        with request.urlopen(f"{BACKEND_URL}/health", timeout=timeout) as response:
            return response.status == 200
    except Exception:
        return False


class BackendProcess:
    """Starts the packaged FastAPI backend unless an external one is running."""

    def __init__(self) -> None:
        self.process: subprocess.Popen | None = None

    def start(self) -> None:
        if os.getenv("FACEAGENT_AUTO_START_BACKEND", "true").lower() not in {"1", "true", "yes", "on"}:
            return
        if self.process is not None and self.process.poll() is None:
            return
        if is_backend_ready():
            return

        env = os.environ.copy()
        env.setdefault("FACEAGENT_BACKEND_URL", BACKEND_URL)

        # Import unified canonical DB path resolver
        try:
            from python_recognizer.store import get_platform_db_path
            # Desktop builds must always use this machine's own user data
            # directory, even if PYTHON_DB_PATH was inherited from a dev shell.
            db_path = get_platform_db_path()
        except Exception:
            db_path = writable_app_dir() / "data" / "app.db"

        snapshot_path = db_path.parent.parent / "snapshots" if not getattr(sys, "frozen", False) else writable_app_dir() / "snapshots"
        self._copy_initial_data(db_path, snapshot_path)
        env["PYTHON_DB_PATH"] = str(db_path)
        os.environ["PYTHON_DB_PATH"] = str(db_path)
        env.setdefault("SNAPSHOT_PATH", str(snapshot_path))
        bundled_model_dir = bundled_resource("insightface_models")
        if bundled_model_dir.exists():
            env.setdefault("INSIGHTFACE_MODEL_DIR", str(bundled_model_dir))
        bundled_ffmpeg = bundled_resource("ffmpeg_runtime", "ffmpeg")
        if bundled_ffmpeg.exists():
            env.setdefault("FFMPEG_PATH", str(bundled_ffmpeg))

        if getattr(sys, "frozen", False):
            args = [sys.executable, "--backend"]
        else:
            args = [
                sys.executable,
                "-m",
                "uvicorn",
                "python_recognizer.app:app",
                "--host",
                BACKEND_HOST,
                "--port",
                BACKEND_PORT,
                "--no-access-log",
            ]

        log_handle = None
        stdout = None
        stderr = None
        if getattr(sys, "frozen", False):
            log_path = writable_app_dir() / "logs" / "backend.log"
            try:
                log_path.parent.mkdir(parents=True, exist_ok=True)
                log_handle = open(log_path, "a", encoding="utf-8")
            except OSError:
                # Always retain diagnostics even if the installed data folder
                # is unavailable or blocked by Windows permissions.
                fallback_dir = Path(os.getenv("TEMP", str(Path.cwd()))) / "OtenceIntelligence"
                fallback_dir.mkdir(parents=True, exist_ok=True)
                log_path = fallback_dir / "backend.log"
                log_handle = open(log_path, "a", encoding="utf-8")
            log_handle.write(f"\n--- Backend start {time.ctime()} ---\n")
            log_handle.flush()
            stdout = log_handle
            stderr = subprocess.STDOUT

        popen_kwargs = {"env": env, "stdout": stdout, "stderr": stderr}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

        self.process = subprocess.Popen(args, **popen_kwargs)
        if log_handle is not None:
            log_handle.close()
        if not self._wait_until_ready():
            # Do not leave a crash-looping child behind. The caller can show a
            # single startup failure and the user can retry deliberately.
            self.stop()
            exit_code = self.process.poll()
            detail = f" (exit code {exit_code})" if exit_code is not None else ""
            raise RuntimeError(f"Local backend failed to become ready{detail}; see backend.log")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def _wait_until_ready(self) -> bool:
        for _ in range(40):
            if is_backend_ready(timeout=0.5):
                return True
            time.sleep(0.25)
        return False

    def _copy_initial_data(self, db_path: Path, snapshot_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.mkdir(parents=True, exist_ok=True)


def writable_app_dir() -> Path:
    root = Path.home() / "Library" / "Application Support" / "FaceAgent"
    if sys.platform.startswith("win"):
        root = Path(os.getenv("APPDATA", str(Path.home()))) / "FaceAgent"
    elif sys.platform.startswith("linux"):
        root = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "FaceAgent"
    try:
        root.mkdir(parents=True, exist_ok=True)
        return root
    except PermissionError:
        fallback = Path(__file__).resolve().parents[1] / ".faceagent"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def bundled_resource(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base.joinpath(*parts)
