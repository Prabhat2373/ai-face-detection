"""Settings page with sliders and inputs that save variables to the project's .env file."""

from __future__ import annotations

import os
import re
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSlider, QDoubleSpinBox, QSpinBox, 
    QMessageBox, QFormLayout, QGroupBox, QCheckBox
)
from PySide6.QtCore import Qt

from ..widgets import SectionHeader

class SettingsPage(QWidget):
    """UI settings panel representing .env file configuration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.env_path = Path(__file__).resolve().parents[2] / ".env"
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        self._main_layout = QVBoxLayout(self._container)
        self._main_layout.setContentsMargins(24, 24, 24, 24)
        self._main_layout.setSpacing(20)

        # Page header
        header = QWidget()
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(4)
        title = QLabel("Settings")
        title.setProperty("class", "page-title")
        desc = QLabel("Configure face recognition parameters, stream frame rates, and alarms")
        desc.setProperty("class", "page-desc")
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        self._main_layout.addWidget(header)

        # Form Container
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(12)

        # --- Accuracy Parameters Group ---
        group_accuracy = QGroupBox("Accuracy & Detection")
        group_accuracy.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding-top: 16px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        acc_layout = QFormLayout(group_accuracy)

        self.det_threshold = QDoubleSpinBox()
        self.det_threshold.setRange(0.1, 1.0)
        self.det_threshold.setSingleStep(0.05)
        self.det_threshold.setDecimals(2)
        acc_layout.addRow(QLabel("Detection Threshold (DETECTION_THRESHOLD):"), self.det_threshold)

        self.match_threshold = QDoubleSpinBox()
        self.match_threshold.setRange(0.1, 1.0)
        self.match_threshold.setSingleStep(0.05)
        self.match_threshold.setDecimals(2)
        acc_layout.addRow(QLabel("Matching Threshold (MATCH_THRESHOLD):"), self.match_threshold)

        form_layout.addRow(group_accuracy)

        # --- Camera & Stream Group ---
        group_stream = QGroupBox("Camera & Stream Options")
        group_stream.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding-top: 16px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        stream_layout = QFormLayout(group_stream)

        self.stream_fps = QSpinBox()
        self.stream_fps.setRange(1, 60)
        stream_layout.addRow(QLabel("Ingestion Frame Rate (STREAM_FRAME_RATE):"), self.stream_fps)

        self.process_fps = QSpinBox()
        self.process_fps.setRange(1, 60)
        stream_layout.addRow(QLabel("Processing Frame Rate (FRAME_RATE):"), self.process_fps)

        form_layout.addRow(group_stream)

        # --- Alarms & Confirmation Group ---
        group_alarm = QGroupBox("Alarms & Grace Periods")
        group_alarm.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding-top: 16px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        alarm_layout = QFormLayout(group_alarm)

        self.alarm_enabled = QCheckBox("Enable Audio Alarm")
        alarm_layout.addRow(self.alarm_enabled)

        self.confirm_frames = QSpinBox()
        self.confirm_frames.setRange(1, 30)
        alarm_layout.addRow(QLabel("Alarm Confirmation Frames:"), self.confirm_frames)

        self.min_det_conf = QDoubleSpinBox()
        self.min_det_conf.setRange(0.1, 1.0)
        self.min_det_conf.setSingleStep(0.05)
        self.min_det_conf.setDecimals(2)
        alarm_layout.addRow(QLabel("Alarm Min Detection Confidence:"), self.min_det_conf)

        self.grace_ms = QSpinBox()
        self.grace_ms.setRange(100, 10000)
        self.grace_ms.setSingleStep(500)
        self.grace_ms.setSuffix(" ms")
        alarm_layout.addRow(QLabel("Recognition Grace Period:"), self.grace_ms)

        form_layout.addRow(group_alarm)

        self._main_layout.addWidget(form_container)

        # Buttons
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setProperty("class", "primary")
        self.save_btn.setMinimumWidth(120)
        self.save_btn.setStyleSheet("QPushButton { background:#1a73e8; color:#ffffff; border:1px solid #1a73e8; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { background:#1765cc; border-color:#1765cc; }")
        self.save_btn.clicked.connect(self.on_save)
        
        self.reset_btn = QPushButton("Reset to Current")
        self.reset_btn.setMinimumWidth(120)
        self.reset_btn.setStyleSheet("QPushButton { background:#ffffff; color:#111827; border:1px solid #e5e7eb; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { border-color:#1a73e8; background:#eef4ff; }")
        self.reset_btn.clicked.connect(self.refresh)

        btn_layout.addStretch()
        btn_layout.addWidget(self.reset_btn)
        btn_layout.addWidget(self.save_btn)
        self._main_layout.addLayout(btn_layout)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        """Read .env variables and load them into UI widgets."""
        env = self._read_env()
        
        # Accuracy group
        self.det_threshold.setValue(float(env.get("PYTHON_DETECTION_THRESHOLD", env.get("DETECTION_THRESHOLD", "0.7"))))
        self.match_threshold.setValue(float(env.get("PYTHON_MATCH_THRESHOLD", env.get("MATCH_THRESHOLD", "0.58"))))

        # Stream group
        self.stream_fps.setValue(int(env.get("STREAM_FRAME_RATE", "15")))
        self.process_fps.setValue(int(env.get("FRAME_RATE", "15")))

        # Alarms group
        self.alarm_enabled.setChecked(env.get("ALARM_ENABLED", "false").lower() == "true")
        self.confirm_frames.setValue(int(env.get("ALARM_UNKNOWN_CONFIRMATION_FRAMES", "3")))
        self.min_det_conf.setValue(float(env.get("ALARM_MIN_DETECTION_CONFIDENCE", "0.75")))
        self.grace_ms.setValue(int(env.get("RECOGNITION_GRACE_MS", "3000")))

    def on_save(self):
        """Write UI widget values to the .env file."""
        updates = {
            "PYTHON_DETECTION_THRESHOLD": f"{self.det_threshold.value():.2f}",
            "DETECTION_THRESHOLD": f"{self.det_threshold.value():.2f}",
            "PYTHON_MATCH_THRESHOLD": f"{self.match_threshold.value():.2f}",
            "MATCH_THRESHOLD": f"{self.match_threshold.value():.2f}",
            "STREAM_FRAME_RATE": str(self.stream_fps.value()),
            "FRAME_RATE": str(self.process_fps.value()),
            "ALARM_ENABLED": "true" if self.alarm_enabled.isChecked() else "false",
            "ALARM_UNKNOWN_CONFIRMATION_FRAMES": str(self.confirm_frames.value()),
            "ALARM_MIN_DETECTION_CONFIDENCE": f"{self.min_det_conf.value():.2f}",
            "KNOWN_GRACE_MS": str(self.grace_ms.value()),
            "RECOGNITION_GRACE_MS": str(self.grace_ms.value()),
        }

        try:
            self._write_env(updates)
            QMessageBox.information(
                self, 
                "Success", 
                "Settings saved successfully!\n\nPlease restart the application to apply the changes."
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to write settings to .env file:\n{exc}"
            )

    def _read_env(self) -> dict[str, str]:
        env = {}
        if not self.env_path.exists():
            return env
        try:
            with open(self.env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        env[k.strip()] = v.strip()
        except Exception:
            pass
        return env

    def _write_env(self, updates: dict[str, str]):
        lines = []
        if self.env_path.exists():
            with open(self.env_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

        written_keys = set()
        new_lines = []

        # Replace existing values in the file
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, v = stripped.split("=", 1)
                k = k.strip()
                if k in updates:
                    new_lines.append(f"{k}={updates[k]}\n")
                    written_keys.add(k)
                    continue
            new_lines.append(line)

        # Append keys that were not originally present in the file
        for k, v in updates.items():
            if k not in written_keys:
                new_lines.append(f"{k}={v}\n")

        with open(self.env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
