"""Launch and manage the local backend for the desktop app."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib import request


BACKEND_URL = os.getenv("FACEAGENT_BACKEND_URL", "http://127.0.0.1:5055").rstrip("/")
BACKEND_HOST = os.getenv("FACEAGENT_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = os.getenv("FACEAGENT_BACKEND_PORT", "5055")


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
        if is_backend_ready():
            return

        env = os.environ.copy()
        env.setdefault("FACEAGENT_BACKEND_URL", BACKEND_URL)
        db_path = writable_app_dir() / "data" / "app.db"
        snapshot_path = writable_app_dir() / "snapshots"
        self._copy_initial_data(db_path, snapshot_path)
        env.setdefault("PYTHON_DB_PATH", str(db_path))
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
            ]

        log_handle = None
        stdout = None
        stderr = None
        if getattr(sys, "frozen", False):
            log_path = writable_app_dir() / "logs" / "backend.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_handle = open(log_path, "a", encoding="utf-8")
            stdout = log_handle
            stderr = subprocess.STDOUT

        self.process = subprocess.Popen(args, env=env, stdout=stdout, stderr=stderr)
        if log_handle is not None:
            log_handle.close()
        self._wait_until_ready()

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def _wait_until_ready(self) -> None:
        for _ in range(40):
            if is_backend_ready(timeout=0.5):
                return
            time.sleep(0.25)

    def _copy_initial_data(self, db_path: Path, snapshot_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.mkdir(parents=True, exist_ok=True)
        if not db_path.exists():
            bundled_db = bundled_resource("python_recognizer", "data", "app.db")
            if bundled_db.exists():
                shutil.copy2(bundled_db, db_path)


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
