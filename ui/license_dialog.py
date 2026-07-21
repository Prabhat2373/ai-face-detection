# working_face_detection/ui/license_dialog.py
"""
Activation dialog for FaceAgent.

Responsibilities:
- Display the Machine ID (from licenses.manager.get_machine_fingerprint())
- Allow copying Machine ID to clipboard
- Allow saving a Machine Request file containing the Machine ID
- Allow importing a vendor-provided license file:
  - copy selected file to the per-user application data folder as "license.key"
  - do NOT perform cryptographic verification here (launcher is responsible)
- Provide clear success/failure feedback to the user

This dialog is intentionally UI-only and does not contain licensing business logic.
The launcher will verify any installed license after the dialog exits.
"""

from __future__ import annotations

import shutil
import sys
import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QApplication,
)
from PySide6.QtGui import QIcon
from PySide6.QtCore import Qt

# Try to import the machine fingerprint provider and writable_app_dir
try:
    from licenses.manager import get_machine_fingerprint  # type: ignore
except Exception:
    def get_machine_fingerprint() -> str:  # fallback stub
        return "UNKNOWN-FINGERPRINT"

try:
    from ui.backend_process import writable_app_dir  # type: ignore
except Exception:
    def writable_app_dir() -> Path:
        # Fallback for dev: use a per-user folder
        return Path.home() / ".faceagent"


DEFAULT_LICENSE_FILENAME = "license.key"
DEFAULT_REQUEST_FILENAME = "FaceAgent_MachineRequest.json"


class LicenseDialog(QDialog):
    """Modal dialog used for activation (show Machine ID and import license)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("FaceAgent Activation")
        try:
            # If project provides an icon resource, you can set it here.
            icon_path = Path(__file__).resolve().parents[2] / "resources" / "icon.ico"
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
        except Exception:
            pass

        self.fingerprint = self._compute_fingerprint()
        self._init_ui()

    def _compute_fingerprint(self) -> str:
        try:
            fp = get_machine_fingerprint()
            return fp or "UNKNOWN-FINGERPRINT"
        except Exception:
            return "UNKNOWN-FINGERPRINT"

    def _init_ui(self) -> None:
        self.setMinimumWidth(640)

        layout = QVBoxLayout(self)

        label = QLabel(
            "Activation is required. Please send the Machine ID to the vendor to receive a license.key file.\n\n"
            "You can copy the Machine ID, save a Machine Request file, or import a license file if you already have one."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        # Machine ID display (read-only)
        id_label = QLabel("Machine ID:")
        layout.addWidget(id_label)

        self.id_field = QLineEdit(self.fingerprint)
        self.id_field.setReadOnly(True)
        layout.addWidget(self.id_field)

        # Optional company input for Machine Request metadata (previous code referenced
        # self.company_input when saving the Machine Request; ensure the field exists).
        company_label = QLabel("Company (optional):")
        layout.addWidget(company_label)
        self.company_input = QLineEdit()
        self.company_input.setPlaceholderText("Organization or company name (optional)")
        layout.addWidget(self.company_input)

        # Buttons for copy and save
        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton("Copy Machine ID")
        self.copy_btn.clicked.connect(self._on_copy)
        btn_row.addWidget(self.copy_btn)

        self.save_request_btn = QPushButton("Save Machine Request...")
        self.save_request_btn.clicked.connect(self._on_save_request)
        btn_row.addWidget(self.save_request_btn)

        layout.addLayout(btn_row)

        # Import license area
        import_label = QLabel("Import license.key")
        layout.addWidget(import_label)

        imp_row = QHBoxLayout()
        self.import_path_field = QLineEdit()
        self.import_path_field.setReadOnly(True)
        imp_row.addWidget(self.import_path_field)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.clicked.connect(self._on_browse)
        imp_row.addWidget(self.browse_btn)

        self.import_btn = QPushButton("Install License")
        self.import_btn.clicked.connect(self._on_import)
        self.import_btn.setEnabled(False)
        imp_row.addWidget(self.import_btn)

        layout.addLayout(imp_row)

        # Footer: status and action buttons
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        footer = QHBoxLayout()
        footer.addStretch(1)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self._on_cancel)
        footer.addWidget(self.cancel_btn)

        self.finish_btn = QPushButton("Finish (after installing license)")
        # This Finish button simply closes the dialog with Accepted; launcher will re-check license.
        self.finish_btn.clicked.connect(self._on_finish)
        footer.addWidget(self.finish_btn)

        layout.addLayout(footer)

    def _on_copy(self) -> None:
        clipboard = QApplication.clipboard()
        clipboard.setText(self.fingerprint)
        QMessageBox.information(self, "Machine ID Copied", "Machine ID copied to clipboard.")

    def _on_save_request(self) -> None:
        # Suggest a default filename on the Desktop
        default = str(Path.home() / "Desktop" / DEFAULT_REQUEST_FILENAME)
        path, _ = QFileDialog.getSaveFileName(self, "Save Machine Request", default, "JSON Files (*.json);;All Files (*)")
        if not path:
            return
        payload = {
            "machine_id": self.fingerprint,
            "app_version": os.getenv("FACEAGENT_VERSION", "1.0.0"),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "company": self.company_input.text().strip() or None,
        }
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, separators=(",", ":"), ensure_ascii=False, indent=2)
            QMessageBox.information(self, "Saved", f"Machine Request saved to:\n{path}")
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", f"Unable to save Machine Request:\n{exc}")

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Select license.key file", str(Path.home()), "License Files (*.key *.bin *.lic);;All Files (*)")
        if not path:
            return
        self.import_path_field.setText(path)
        self.import_btn.setEnabled(True)
        self.status.setText("")

    def _on_import(self) -> None:
        src = self.import_path_field.text().strip()
        if not src:
            QMessageBox.warning(self, "No file", "Please select a license file to import.")
            return
        src_path = Path(src)
        if not src_path.exists() or not src_path.is_file():
            QMessageBox.warning(self, "Not found", "Selected license file not found.")
            return

        try:
            target_dir = writable_app_dir()
        except Exception:
            target_dir = Path.home() / ".faceagent"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # fallback: attempt to continue; copy may fail
            pass

        dest = target_dir / DEFAULT_LICENSE_FILENAME
        try:
            # Copy the selected license file to per-user location.
            shutil.copy2(str(src_path), str(dest))
        except Exception as exc:
            QMessageBox.critical(self, "Install failed", f"Failed to install license:\n{exc}")
            self.status.setText(f"Install failed: {exc}")
            return

        # Inform user that license was installed and launcher will verify it.
        QMessageBox.information(self, "License Installed", f"The license file was installed to:\n{dest}\n\nThe application will verify it now.")
        self.status.setText(f"License installed to: {dest}")
        # Enable Finish; let launcher re-check the license and continue
        self.import_btn.setEnabled(False)
        self.browse_btn.setEnabled(False)
        self.finish_btn.setEnabled(True)
        # Accept to indicate the user finished import successfully
        self.accept()

    def _on_finish(self) -> None:
        # User finished activation steps (may or may not have imported license)
        self.accept()

    def _on_cancel(self) -> None:
        # User cancelled activation process
        self.reject()


if __name__ == "__main__":
    # Run the dialog standalone for manual testing. Exits 0 on accept, 2 on cancel.
    app = QApplication(sys.argv)
    dlg = LicenseDialog()
    res = dlg.exec()
    if res == QDialog.Accepted:
        print("Dialog accepted")
        sys.exit(0)
    else:
        print("Dialog cancelled")
        sys.exit(2)
