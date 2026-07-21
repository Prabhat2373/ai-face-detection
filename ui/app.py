#!/usr/bin/env python3
"""FaceAgent Desktop - Native PySide6 application for face detection management.

This entrypoint supports an activation mode used to present the Machine ID and
allow the user to import a vendor-supplied license file. Activation mode is
invoked by passing the `--activation` flag to the UI executable.

Important:
- The UI never performs cryptographic verification. It only displays the
  Machine ID and copies the chosen license file into the per-user data folder.
- The launcher (application entrypoint) is responsible for verifying the
  license cryptographically and deciding whether to continue launching the app.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

# Ensure the project root is on the path so we can import ui and packages
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtCore import Qt

from ui.styles import build_stylesheet
from ui.main_window import MainWindow
from ui.backend_process import BackendProcess


def run_backend():
    """Run the FastAPI backend in-process (used when the UI is asked to host it)."""
    import uvicorn  # local import to avoid heavy deps unless needed
    from python_recognizer.app import app as backend_app  # type: ignore

    uvicorn.run(
        backend_app,
        host=os.getenv("FACEAGENT_BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("FACEAGENT_BACKEND_PORT", "5055")),
        log_level=os.getenv("FACEAGENT_BACKEND_LOG_LEVEL", "warning"),
    )


def activation_mode() -> int:
    """
    Show the Activation dialog and return an exit code:
      0 = user accepted / imported license (launcher will verify)
      2 = user cancelled activation
    """
    # Import here to avoid pulling UI dependencies unless activation requested
    from ui.license_dialog import LicenseDialog  # type: ignore

    # Enable high-DPI behavior
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("FaceAgent")
    app.setApplicationDisplayName("FaceAgent Desktop - Activation")
    app.setOrganizationName("FaceAgent")

    # Apply global stylesheet (optional); activation UI can use same theme
    app.setStyleSheet(build_stylesheet(os.getenv("FACEAGENT_THEME", "light")))

    dialog = LicenseDialog()
    result = dialog.exec()

    # QDialog.Accepted => user finished activation/import step
    if result == QDialog.Accepted:
        return 0
    return 2


def main():
    # Special modes first
    if "--backend" in sys.argv:
        # Run the backend process in the UI process (used by frozen builds if needed)
        run_backend()
        return

    if "--activation" in sys.argv:
        # Activation mode: show the activation/import dialog and exit.
        # Remove the flag so QApplication argument parsing is clean.
        try:
            sys.argv.remove("--activation")
        except ValueError:
            pass
        rc = activation_mode()
        # Return a non-zero code on cancel so the launcher can detect it.
        sys.exit(rc)

    # Normal application startup: start backend (if auto-started) and show UI
    backend = None
    # Respect env/flags to avoid auto-start when managed externally by the launcher
    no_auto_flag = "--no-auto-backend" in sys.argv
    env_no_auto = os.getenv("FACEAGENT_NO_AUTO_START_BACKEND", "").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    no_auto_start = no_auto_flag or env_no_auto

    if no_auto_flag:
        try:
            sys.argv.remove("--no-auto-backend")
        except ValueError:
            pass

    if not no_auto_start:
        backend = BackendProcess()
        backend.start()
    else:
        # Create BackendProcess instance so stop() is callable in finally block.
        backend = BackendProcess()

    # Enable high-DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("FaceAgent")
    app.setApplicationDisplayName("FaceAgent Desktop")
    app.setOrganizationName("FaceAgent")

    # Apply global stylesheet
    app.setStyleSheet(build_stylesheet(os.getenv("FACEAGENT_THEME", "light")))

    # Create and show window
    window = MainWindow()
    window.show()

    try:
        # Run application event loop
        sys.exit(app.exec())
    finally:
        # Ensure backend started by this UI is stopped on exit.
        if backend:
            try:
                backend.stop()
            except Exception:
                pass


if __name__ == "__main__":
    main()
