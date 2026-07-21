#!/usr/bin/env python3
"""
License Manager GUI (Vendor-only)

This PySide6 application lets the vendor:
- Import a Machine Request JSON (produced by the customer application)
- Enter company name
- Choose license type (trial, professional, enterprise, lifetime)
- Choose expiry date (optional; lifetime implies no expiry)
- Enter enabled features (comma-separated)
- Point to the vendor private key (PEM)
- Generate and save a license.key using the existing generator logic

This application intentionally re-uses the project's `licenses.generator`
implementation for signing/encrypting licenses. The private key is selected
at runtime by the vendor; it is never stored in the repository.

Run: (from project root)
    python -m working_face_detection.license_manager.ui.app_gui
or
    python working_face_detection/license_manager/ui/app_gui.py
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# PySide6 imports
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QFileDialog,
    QMessageBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QVBoxLayout,
    QFormLayout,
)
from PySide6.QtCore import Qt, QDate

# Try to import the generator from the project's licenses package. If not available,
# we keep a None placeholder and show an error if the vendor tries to generate.
try:
    from licenses.generator import create_license_file  # type: ignore
except Exception:
    create_license_file = None  # type: ignore


class LicenseManagerWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FaceAgent — License Manager (Vendor)")
        self.setMinimumSize(720, 480)
        self._build_ui()

    def _build_ui(self) -> None:
        main = QVBoxLayout(self)

        # Machine Request import
        form = QFormLayout()
        self.request_path = QLineEdit()
        self.request_browse = QPushButton("Import Machine Request...")
        self.request_browse.clicked.connect(self.on_browse_request)
        h_req = QHBoxLayout()
        h_req.addWidget(self.request_path)
        h_req.addWidget(self.request_browse)
        form.addRow(QLabel("Machine Request (JSON):"), h_req)

        # Company
        self.company = QLineEdit()
        form.addRow(QLabel("Company (optional):"), self.company)

        # License type
        self.license_type = QComboBox()
        self.license_type.addItems(["trial", "professional", "enterprise", "lifetime"])
        form.addRow(QLabel("License Type:"), self.license_type)

        # Expiry date (optional); disabled for 'lifetime'
        self.expiry_date = QDateEdit()
        self.expiry_date.setCalendarPopup(True)
        self.expiry_date.setDate(QDate.currentDate().addDays(30))
        form.addRow(QLabel("Expiry Date (optional):"), self.expiry_date)

        # Features (comma-separated)
        self.features = QLineEdit()
        form.addRow(QLabel("Features (comma-separated):"), self.features)

        # Private key selection
        self.privkey_path = QLineEdit()
        self.privkey_browse = QPushButton("Select Private Key PEM...")
        self.privkey_browse.clicked.connect(self.on_browse_privkey)
        h_key = QHBoxLayout()
        h_key.addWidget(self.privkey_path)
        h_key.addWidget(self.privkey_browse)
        form.addRow(QLabel("Private Key (PEM):"), h_key)

        # Private key passphrase
        self.privkey_pass = QLineEdit()
        self.privkey_pass.setEchoMode(QLineEdit.Password)
        form.addRow(QLabel("Private Key Passphrase (optional):"), self.privkey_pass)

        # Output license path
        self.out_path = QLineEdit()
        self.out_browse = QPushButton("Save license.key As...")
        self.out_browse.clicked.connect(self.on_browse_out)
        h_out = QHBoxLayout()
        h_out.addWidget(self.out_path)
        h_out.addWidget(self.out_browse)
        form.addRow(QLabel("Output License File:"), h_out)

        main.addLayout(form)

        # Status / log area
        main.addWidget(QLabel("Status:"))
        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setFixedHeight(120)
        main.addWidget(self.status)

        # Buttons
        btn_row = QHBoxLayout()
        self.generate_btn = QPushButton("Generate License")
        self.generate_btn.clicked.connect(self.on_generate)
        self.quit_btn = QPushButton("Quit")
        self.quit_btn.clicked.connect(self.close)
        btn_row.addStretch(1)
        btn_row.addWidget(self.generate_btn)
        btn_row.addWidget(self.quit_btn)
        main.addLayout(btn_row)

        # Wire license_type changes to enable/disable expiry
        self.license_type.currentTextChanged.connect(self.on_license_type_change)
        self.on_license_type_change(self.license_type.currentText())

    def append_status(self, text: str) -> None:
        ts = datetime.now(timezone.utc).astimezone().isoformat()
        self.status.append(f"[{ts}] {text}")

    def on_browse_request(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Machine Request JSON",
            str(Path.home()),
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        self.request_path.setText(path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            company = data.get("company")
            if company:
                self.company.setText(str(company))
            self.append_status(f"Loaded Machine Request: {path}")
        except Exception as exc:
            self.append_status(f"Failed to load Machine Request: {exc}")
            QMessageBox.critical(self, "Invalid Request", f"Failed to read Machine Request:\n{exc}")

    def on_browse_privkey(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Private Key PEM",
            str(Path.home()),
            "PEM Files (*.pem);;All Files (*)",
        )
        if path:
            self.privkey_path.setText(path)

    def on_browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save license.key As",
            str(Path.home() / "license.key"),
            "License files (*.key);;All Files (*)",
        )
        if path:
            self.out_path.setText(path)

    def on_license_type_change(self, txt: str) -> None:
        if txt == "lifetime":
            self.expiry_date.setEnabled(False)
        else:
            self.expiry_date.setEnabled(True)

    def on_generate(self) -> None:
        # Validate inputs
        req_path = self.request_path.text().strip()
        if not req_path:
            QMessageBox.warning(self, "Missing", "Please import a Machine Request JSON first.")
            return
        try:
            with open(req_path, "r", encoding="utf-8") as fh:
                req = json.load(fh)
        except Exception as exc:
            QMessageBox.critical(self, "Invalid", f"Failed to read Machine Request:\n{exc}")
            return

        fingerprint = req.get("machine_id")
        if not fingerprint:
            QMessageBox.critical(self, "Invalid", "Machine Request JSON missing 'machine_id'.")
            return

        license_type = self.license_type.currentText()
        # expiry calculation: if lifetime, allow no expiry. Otherwise use selected date if set.
        expires_iso = None
        if license_type != "lifetime":
            date_q = self.expiry_date.date()
            # Use midnight UTC of chosen date
            expires_dt = datetime(date_q.year(), date_q.month(), date_q.day(), tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            if expires_dt <= now:
                QMessageBox.warning(self, "Expiry", "Expiry date must be in the future.")
                return
            expires_iso = expires_dt.isoformat()

        out_path_str = self.out_path.text().strip()
        if not out_path_str:
            QMessageBox.warning(self, "Output", "Please select an output path for license.key.")
            return
        out_path = Path(out_path_str)

        priv_path = self.privkey_path.text().strip()
        if not priv_path:
            QMessageBox.warning(self, "Private key", "Please select your private key PEM.")
            return
        priv_path = Path(priv_path)

        passphrase = self.privkey_passphrase()  # may be None

        features_text = self.features_text()
        meta = {
            "company": self.company.text().strip() or None,
            "features": features_text,
        }

        # call the generator
        if create_license_file is None:
            QMessageBox.critical(self, "Unavailable", "License generator is not available in this environment.")
            return

        try:
            self.append_status("Generating license...")
            # create_license_file(private_key_path, fingerprint, license_type, days, expires_iso, meta_json, out_path, passphrase, allow_no_expiry)
            # For trial we can set days or use expires_iso; here use expires_iso if provided; otherwise for trial default to 14 days
            days = None
            if license_type == "trial" and expires_iso is None:
                days = 14
            create_license_file(
                private_key_path=priv_path,
                fingerprint=fingerprint,
                license_type=license_type,
                days=days,
                expires_iso=expires_iso,
                meta_json=json.dumps(meta),
                out_path=out_path,
                passphrase=passphrase.encode("utf-8") if passphrase else None,
                allow_no_expiry=(license_type == "lifetime"),
            )
            self.append_status(f"License written to: {out_path}")
            QMessageBox.information(self, "Success", f"License generated and saved to:\n{out_path}")
        except Exception as exc:
            tb = traceback.format_exc()
            self.append_status(f"Generation failed: {exc}\\n{tb}")
            QMessageBox.critical(self, "Error", f"Failed to generate license:\n{exc}")

    def privkey_passphrase(self) -> Optional[str]:
        # Simple prompt using QInputDialog would be better, but to keep UI minimal we ask via a file-based dialog field
        # For now, reuse a modal input via QFileDialog not ideal; we can implement a simple QInputDialog when needed.
        # If no passphrase field exists, return None.
        # Provide a quick text input by opening a small dialog:
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Private Key Passphrase", "Passphrase (leave blank if none):", QLineEdit.Password)
        if ok:
            return text or None
        return None

    def features_text(self) -> list[str]:
        # For simplicity take features from the features QLineEdit if present (backwards compatible)
        # If no features field present in this GUI (we didn't add an explicit QLineEdit), return empty.
        try:
            # Some versions may have feature QLineEdit; attempt to read it
            val = getattr(self, "features", None)
            if val and isinstance(val, QLineEdit):
                raw = val.text()
                return [f.strip() for f in raw.split(",") if f.strip()]
        except Exception:
            pass
        return []


def run_as_standalone():
    app = QApplication([])
    win = LicenseManagerWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_as_standalone()
