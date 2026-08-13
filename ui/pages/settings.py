"""Settings page that saves variables directly to the SQLite settings database table."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QMessageBox, QFormLayout, QGroupBox,
    QCheckBox, QComboBox
)
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from ..database import Database
from ..backend_process import writable_app_dir


PERFORMANCE_PROFILES = {
    "low": {
        "label": "Low memory (recommended for 8 GB laptops)",
        "model": "buffalo_s",
        "det_size": 320,
        "max_dim": 360,
        "stream_fps": 3,
        "detection_fps": 1,
        "auto_start": False,
        "description": "Uses the least RAM and CPU. Starts cameras only when you press Start.",
    },
    "balanced": {
        "label": "Balanced (recommended for most computers)",
        "model": "buffalo_s",
        "det_size": 480,
        "max_dim": 480,
        "stream_fps": 5,
        "detection_fps": 3,
        "auto_start": False,
        "description": "Good recognition quality with moderate resource usage.",
    },
    "high": {
        "label": "High accuracy (requires more RAM)",
        "model": "buffalo_l",
        "det_size": 640,
        "max_dim": 640,
        "stream_fps": 10,
        "detection_fps": 4,
        "auto_start": True,
        "description": "Best recognition quality, but may be slow on 8 GB laptops.",
    },
    "very_high": {
        "label": "Very High Accuracy (recommended for high-end PCs / GPUs)",
        "model": "buffalo_l",
        "det_size": 1080,
        "max_dim": 1080,
        "stream_fps": 15,
        "detection_fps": 6,
        "auto_start": True,
        "description": "Maximum accuracy with large detection sizes and fast tracking. Requires dedicated hardware.",
    },
}

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
        desc = QLabel("Choose a simple performance profile for your computer")
        desc.setProperty("class", "page-desc")
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        self._main_layout.addWidget(header)

        # Form Container
        form_container = QWidget()
        form_layout = QFormLayout(form_container)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(12)

        # --- Performance Group ---
        group_performance = QGroupBox("Performance Profile")
        group_performance.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding-top: 16px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        performance_layout = QFormLayout(group_performance)

        self.performance_profile = QComboBox()
        try:
            from PySide6.QtWidgets import QListView
            self.performance_profile.setView(QListView())
            view = self.performance_profile.view()
            if view is not None:
                view.setStyleSheet("background:#ffffff; color:#111827; selection-background-color:#e8f0fe; selection-color:#ffffff;")
        except Exception:
            pass
        for key, profile in PERFORMANCE_PROFILES.items():
            self.performance_profile.addItem(profile["label"], key)
        self.performance_profile.currentIndexChanged.connect(self._update_profile_description)

        self.profile_description = QLabel()
        self.profile_description.setWordWrap(True)
        self.profile_description.setStyleSheet("color: #6b7280; font-size: 11px; margin-top: 2px;")

        performance_layout.addRow(QLabel("Computer performance:"), self.performance_profile)
        performance_layout.addRow(self.profile_description)
        form_layout.addRow(group_performance)

        # --- Alarms & Weapon Detection Group ---
        group_alarm = QGroupBox("Alarms & Threat Detection")
        group_alarm.setStyleSheet("QGroupBox { font-weight: bold; border: 1px solid #e5e7eb; border-radius: 8px; margin-top: 12px; padding-top: 16px; } QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }")
        alarm_layout = QFormLayout(group_alarm)

        self.alarm_enabled = QCheckBox("Enable Audio Alarm Sound")
        alarm_layout.addRow(self.alarm_enabled)

        self.weapon_enabled = QCheckBox("Enable Real-time Weapon Detection (YOLO)")
        alarm_layout.addRow(self.weapon_enabled)

        form_layout.addRow(group_alarm)

        self._main_layout.addWidget(form_container)


        # Buttons
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setProperty("class", "primary")
        self.save_btn.setMinimumWidth(120)
        self.save_btn.setStyleSheet("QPushButton { background:#1a73e8; color:#ffffff; border:1px solid #1a73e8; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { background:#1765cc; border-color:#1765cc; }")
        self.save_btn.clicked.connect(self.on_save)

        # self.seed_btn = QPushButton("Seed Test Data")
        # self.seed_btn.setMinimumWidth(130)
        # self.seed_btn.setStyleSheet("QPushButton { background:#ecfdf5; color:#047857; border:1px solid #a7f3d0; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { background:#d1fae5; border-color:#059669; }")
        # self.seed_btn.clicked.connect(self.on_seed_data)

        self.reset_btn = QPushButton("Reset to Current")
        self.reset_btn.setMinimumWidth(120)
        self.reset_btn.setStyleSheet("QPushButton { background:#ffffff; color:#111827; border:1px solid #e5e7eb; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { border-color:#1a73e8; background:#eef4ff; }")
        self.reset_btn.clicked.connect(self.refresh)

        # btn_layout.addWidget(self.seed_btn)
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
        profile_key = self.db.get_setting("PERFORMANCE_PROFILE", "low").strip().lower()
        profile_idx = self.performance_profile.findData(profile_key)
        self.performance_profile.setCurrentIndex(profile_idx if profile_idx >= 0 else 0)
        self._update_profile_description()

        alarm_val = self.db.get_setting("ALARM_ENABLED", "false").lower() == "true"
        self.alarm_enabled.setChecked(alarm_val)

        weapon_val = self.db.get_setting("WEAPON_DETECTION_ENABLED", "true").lower() in {"true", "1", "yes", "on"}
        self.weapon_enabled.setChecked(weapon_val)

    def on_save(self):
        """Write UI widget values to the DB settings."""
        try:
            profile_key = str(self.performance_profile.currentData())
            profile = PERFORMANCE_PROFILES[profile_key]
            self.db.set_setting("PERFORMANCE_PROFILE", profile_key)
            self.db.set_setting("INSIGHTFACE_MODEL", profile["model"])
            self.db.set_setting("INSIGHTFACE_DET_SIZE", str(profile["det_size"]))
            self.db.set_setting("DETECTION_IMAGE_MAX_DIM", str(profile["max_dim"]))
            self.db.set_setting("STREAM_FRAME_RATE", str(profile["stream_fps"]))
            self.db.set_setting("FRAME_RATE", str(profile["detection_fps"]))
            self.db.set_setting("AUTO_START_DETECTION", "true" if profile["auto_start"] else "false")
            self.db.set_setting("ALARM_ENABLED", "true" if self.alarm_enabled.isChecked() else "false")
            self.db.set_setting("WEAPON_DETECTION_ENABLED", "true" if self.weapon_enabled.isChecked() else "false")
            restart_marker = writable_app_dir() / "restart-requested"

            restart_marker.write_text("settings", encoding="utf-8")
            self._show_light_message(
                QMessageBox.Information,
                "Success",
                "Settings saved successfully!\n\nThe application will now restart to load the new recognition profile.",
            )
            app = QApplication.instance()
            if app is not None:
                app.quit()
        except Exception as exc:
            self._show_light_message(
                QMessageBox.Critical,
                "Error",
                f"Failed to write settings to database:\n{exc}",
            )

    def _show_light_message(self, icon, title: str, message: str) -> None:
        """Show a light confirmation/error dialog regardless of OS theme."""
        box = QMessageBox(self)
        box.setIcon(icon)
        box.setWindowTitle(title)
        box.setText(message)
        box.setStandardButtons(QMessageBox.Ok)
        box.setStyleSheet("""
            QMessageBox {
                background: #ffffff;
                color: #111827;
                border: 1px solid #d1d5db;
            }
            QMessageBox QLabel {
                color: #111827;
                background: #ffffff;
                font-size: 13px;
                font-weight: 600;
                min-width: 360px;
            }
            QMessageBox QPushButton {
                background: #ffffff;
                color: #111827;
                border: 1px solid #9ca3af;
                border-radius: 6px;
                padding: 8px 22px;
                min-width: 72px;
                font-weight: 700;
            }
            QMessageBox QPushButton:hover {
                background: #eef4ff;
                border-color: #1a73e8;
            }
        """)
        box.exec()

    def _update_profile_description(self):
        profile = PERFORMANCE_PROFILES.get(str(self.performance_profile.currentData()))
        if not profile:
            return
        self.profile_description.setText(
            f"{profile['description']}\n"
            f" Recognition: {profile['detection_fps']} FPS  •  Preview: {profile['stream_fps']} FPS"
        )

    def on_seed_data(self):
        """Invoke seed database script to generate sample test data."""
        try:
            from seed_db import seed_database
            seed_database(count_employees=2000, days_history=300)
            QMessageBox.information(
                self,
                "Seeding Complete",
                "Successfully populated high-volume test data!\n\n- 8 Departments\n- 2,000 Employees\n- ~500,000 Attendance records across 300 days\n- Sample Cameras & Alarms"
            )
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Seeding Failed",
                f"Failed to seed test data:\n{exc}"
            )
