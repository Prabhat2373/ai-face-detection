"""Settings page that saves variables directly to the SQLite settings database table."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QMessageBox, QFormLayout, QGroupBox,
    QCheckBox, QComboBox
)
from PySide6.QtCore import Qt

from ..database import Database

class SettingsPage(QWidget):
    """UI settings panel backed by SQLite database config table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database.get()
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
        desc = QLabel("Configure camera stream resolutions and alarm preferences")
        desc.setProperty("class", "page-desc")
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        self._main_layout.addWidget(header)

        # Form Container
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(12)

        # --- Camera & Stream Group ---
        group_stream = QGroupBox("Camera Stream Options")
        group_stream.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding-top: 16px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        stream_layout = QFormLayout(group_stream)

        self.detection_max_dim = QComboBox()
        self.detection_max_dim.addItem("320px (Lowest - High Efficiency)", 320)
        self.detection_max_dim.addItem("480px (Low - Medium-High Efficiency)", 480)
        self.detection_max_dim.addItem("640px (Standard - Balanced)", 640)
        self.detection_max_dim.addItem("960px (High - Resource-Intensive)", 960)
        self.detection_max_dim.addItem("1280px (Highest - Heavy Load)", 1280)
        
        desc_label = QLabel(
            "Note: Lower resolutions drastically improve processing speed, "
            "reduce CPU usage/temperature, and allow you to run more concurrent cameras."
        )
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("color: #6b7280; font-size: 11px; margin-top: 2px;")
        
        stream_layout.addRow(QLabel("Max Image Dimension (DETECTION_IMAGE_MAX_DIM):"), self.detection_max_dim)
        stream_layout.addRow(desc_label)

        form_layout.addRow(group_stream)

        # --- Alarms Group ---
        group_alarm = QGroupBox("Alarms")
        group_alarm.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding-top: 16px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        alarm_layout = QFormLayout(group_alarm)

        self.alarm_enabled = QCheckBox("Enable Audio Alarm")
        alarm_layout.addRow(self.alarm_enabled)

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
        self._main_layout.addStretch()

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        """Read variables from DB settings and load them into UI widgets."""
        try:
            val = int(self.db.get_setting("DETECTION_IMAGE_MAX_DIM", "640"))
        except ValueError:
            val = 640
        idx = self.detection_max_dim.findData(val)
        if idx >= 0:
            self.detection_max_dim.setCurrentIndex(idx)
        else:
            self.detection_max_dim.setCurrentIndex(2)

        alarm_val = self.db.get_setting("ALARM_ENABLED", "false").lower() == "true"
        self.alarm_enabled.setChecked(alarm_val)

    def on_save(self):
        """Write UI widget values to the DB settings."""
        try:
            self.db.set_setting("DETECTION_IMAGE_MAX_DIM", str(self.detection_max_dim.currentData()))
            self.db.set_setting("ALARM_ENABLED", "true" if self.alarm_enabled.isChecked() else "false")
            QMessageBox.information(
                self, 
                "Success", 
                "Settings saved successfully!\n\nPlease restart the application to apply the changes."
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to write settings to database:\n{exc}"
            )
