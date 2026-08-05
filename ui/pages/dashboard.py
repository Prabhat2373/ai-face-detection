"""Dashboard page matching the user's target wireframe UI."""

import os
from datetime import datetime, timezone
from typing import List, Dict, Any

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QScrollArea,
    QPushButton, QSizePolicy
)
from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QFont, QPixmap, QColor
from PySide6.QtSvgWidgets import QSvgWidget

from ..widgets import PaginationWidget, render_empty_table_placeholder, Pill
from ..database import Database


class DashboardCard(QFrame):
    """Stat card replicating the card visual of the mockups."""

    def __init__(self, title: str, value: str, subtext: str, badge_text: str = "", badge_state: str = "success", parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)

        # Styles mirroring target layout: light container, subtle border, rounded corner
        self.setStyleSheet("""
            QFrame {
                background-color: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 8px;
            }
        """)
        self.setMinimumHeight(145)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)

        # Header of card (icon placeholder/badge row)
        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(0)
        top_row.setAlignment(Qt.AlignTop)
        # Select SVG icon name based on title
        svg_map = {
            "Total Employees": "employees.svg",
            "Attendance Rate": "attendance.svg",
            "Unknown Alerts": "alarms.svg",
            "Active Cameras": "cameras.svg"
        }
        svg_filename = svg_map.get(title, "dashboard.svg")
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")
        svg_path = os.path.join(base_dir, svg_filename)

        # Select icon background styling based on card type
        icon_bg = "#eef4ff" if "Employee" in title else "#ecfdf5" if "Rate" in title else "#fee2e2" if "Alerts" in title else "#fff7ed"
        icon_fg = "#1a73e8" if "Employee" in title else "#10b981" if "Rate" in title else "#dc2626" if "Alerts" in title else "#ea580c"

        self.icon_badge = QFrame()
        self.icon_badge.setFixedSize(36, 36)
        self.icon_badge.setStyleSheet(f"""
            background-color: {icon_bg};
            border-radius: 18px;
            border: none;
        """)
        badge_lay = QHBoxLayout(self.icon_badge)
        badge_lay.setContentsMargins(9, 9, 9, 9)
        badge_lay.setSpacing(0)

        if os.path.exists(svg_path):
            svg_widget = QSvgWidget(svg_path)
            svg_widget.setStyleSheet(f"background: transparent; color: {icon_fg}; border: none;")
            badge_lay.addWidget(svg_widget)
        else:
            fallback = QLabel()
            emoji_map = {
                "Total Employees": "👥",
                "Attendance Rate": "⏱️",
                "Unknown Alerts": "🚨",
                "Active Cameras": "📹"
            }
            fallback.setText(emoji_map.get(title, "📊"))
            fallback.setAlignment(Qt.AlignCenter)
            fallback.setStyleSheet("background: transparent; font-size: 14px; border: none;")
            badge_lay.addWidget(fallback)

        top_row.addWidget(self.icon_badge)
        top_row.addStretch()

        if badge_text:
            self.trend_badge = Pill(badge_text, badge_state)
            self.trend_badge.setStyleSheet(f"""
                border: none;
                border-radius: 6px;
            """)
            top_row.addWidget(self.trend_badge)
        layout.addLayout(top_row)

        # Value
        self.value_lbl = QLabel(value)
        self.value_lbl.setStyleSheet("""
            font-size: 26px;
            font-weight: 800;
            color: #111827;
            border: none;
            background: transparent;
        """)
        self.value_lbl.setMinimumHeight(34)
        self.value_lbl.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.value_lbl)

        # Title
        self.title_lbl = QLabel(title)
        self.title_lbl.setStyleSheet("""
            font-size: 14px;
            font-weight: 600;
            color: #4b5563;
            border: none;
            background: transparent;
        """)
        self.title_lbl.setMinimumHeight(18)
        layout.addWidget(self.title_lbl)

        # Subtext
        self.subtext_lbl = QLabel(subtext)
        self.subtext_lbl.setStyleSheet("""
            font-size: 13px;
            color: #6b7280;
            border: none;
            background: transparent;
        """)
        self.subtext_lbl.setMinimumHeight(18)
        layout.addWidget(self.subtext_lbl)

    def update_value(self, value: str, subtext: str):
        self.value_lbl.setText(value)
        self.subtext_lbl.setText(subtext)


class DashboardPage(QWidget):
    """Main dashboard page styled exactly like the provided design layout."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database.get()
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(5000)
        self._refresh_timer.timeout.connect(self.refresh)
        self._refresh_timer.start()
        self.refresh()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Scroll Area for page responsiveness
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        main_layout.addWidget(scroll)

        self._container = QWidget()
        self._container.setStyleSheet("background: transparent;")
        scroll.setWidget(self._container)

        self._content_layout = QVBoxLayout(self._container)
        self._content_layout.setContentsMargins(24, 24, 24, 24)
        self._content_layout.setSpacing(20)

        # 1. Page Header (System Dashboard)
        header_widget = QWidget()
        header_widget.setStyleSheet("""
            background-color: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(16, 14, 16, 14)

        # Left Icon and title texts
        title_box = QHBoxLayout()
        title_box.setSpacing(12)

        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")
        header_svg_path = os.path.join(base_dir, "dashboard.svg")

        header_icon = QFrame()
        header_icon.setFixedSize(40, 40)
        header_icon.setStyleSheet("""
            background-color: #f3f4f6;
            border-radius: 6px;
            border: none;
        """)
        h_icon_lay = QHBoxLayout(header_icon)
        h_icon_lay.setContentsMargins(10, 10, 10, 10)
        h_icon_lay.setSpacing(0)

        if os.path.exists(header_svg_path):
            svg_wid = QSvgWidget(header_svg_path)
            svg_wid.setStyleSheet("background: transparent; color: #1a73e8; border: none;")
            h_icon_lay.addWidget(svg_wid)
        else:
            fallback_icon = QLabel("📊")
            fallback_icon.setStyleSheet("background: transparent; font-size: 18px; border: none;")
            fallback_icon.setAlignment(Qt.AlignCenter)
            h_icon_lay.addWidget(fallback_icon)

        title_box.addWidget(header_icon)

        title_text_layout = QVBoxLayout()
        title_text_layout.setSpacing(2)
        title_lbl = QLabel("System Dashboard")
        title_lbl.setStyleSheet("font-size: 19px; font-weight: 800; color: #111827;outline: none;border: none;")
        subtitle_lbl = QLabel("Real-time operational overview")
        subtitle_lbl.setStyleSheet("font-size: 13px; color: #4b5563;border: none;")
        title_text_layout.addWidget(title_lbl)
        title_text_layout.addWidget(subtitle_lbl)
        title_box.addLayout(title_text_layout)
        header_layout.addLayout(title_box)

        header_layout.addStretch()

        # Breadcrumb trail
        breadcrumb = QLabel("Dashboard  >  Overview")
        breadcrumb.setStyleSheet("font-size: 12px; color: #9ca3af; font-weight: 500;border: none;")
        header_layout.addWidget(breadcrumb)
        self.last_updated_lbl = QLabel("Updated --")
        self.last_updated_lbl.setStyleSheet("font-size: 12px; color: #6b7280; border: none;")
        header_layout.addWidget(self.last_updated_lbl)
        self._content_layout.addWidget(header_widget)

        # 2. KPI Cards Row
        kpis_layout = QHBoxLayout()
        kpis_layout.setSpacing(16)

        self.card_employees = DashboardCard("Total Employees", "0", "0 departments", "--", "success")
        self.card_attendance = DashboardCard("Attendance Rate", "0%", "0 present today", "--", "success")
        self.card_alerts = DashboardCard("Unknown Alerts", "0", "0 alerts pending", "--", "idle")
        self.card_cameras = DashboardCard("Active Cameras", "0", "0 active cameras", "--", "idle")

        kpis_layout.addWidget(self.card_employees)
        kpis_layout.addWidget(self.card_attendance)
        kpis_layout.addWidget(self.card_alerts)
        kpis_layout.addWidget(self.card_cameras)
        self._content_layout.addLayout(kpis_layout)

        # 3. Two-Column Middle Grid: Recent Detections & Department Attendance
        middle_grid = QHBoxLayout()
        middle_grid.setSpacing(20)

        # 3a. Recent Detections Column
        detections_panel = QFrame()
        detections_panel.setStyleSheet("background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;")
        detections_layout = QVBoxLayout(detections_panel)
        detections_layout.setContentsMargins(20, 20, 20, 20)
        detections_layout.setSpacing(12)

        det_header_layout = QVBoxLayout()
        det_header_layout.setSpacing(2)
        det_title = QLabel("Recent Detections")
        det_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #111827; border: none;")
        det_sub = QLabel("Last 5 recognition events")
        det_sub.setStyleSheet("font-size: 13px; color: #4b5563; border: none;")
        det_header_layout.addWidget(det_title)
        det_header_layout.addWidget(det_sub)
        detections_layout.addLayout(det_header_layout)

        # Custom Detections List Widget
        self.detections_list_container = QWidget()
        self.detections_list_container.setStyleSheet("border: none; background: transparent;")
        self.detections_list_layout = QVBoxLayout(self.detections_list_container)
        self.detections_list_layout.setContentsMargins(0, 8, 0, 0)
        self.detections_list_layout.setSpacing(10)
        detections_layout.addWidget(self.detections_list_container)
        detections_layout.addStretch()

        middle_grid.addWidget(detections_panel, 1)

        # 3b. Department Attendance Column
        dept_panel = QFrame()
        dept_panel.setStyleSheet("background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;")
        dept_layout = QVBoxLayout(dept_panel)
        dept_layout.setContentsMargins(20, 20, 20, 20)
        dept_layout.setSpacing(12)

        dept_hdr_layout = QVBoxLayout()
        dept_hdr_layout.setSpacing(2)
        dept_title = QLabel("Department Attendance")
        dept_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #111827; border: none;")
        dept_sub = QLabel("Presence and accuracy by department")
        dept_sub.setStyleSheet("font-size: 13px; color: #4b5563; border: none;")
        dept_hdr_layout.addWidget(dept_title)
        dept_hdr_layout.addWidget(dept_sub)
        dept_layout.addLayout(dept_hdr_layout)

        # Table matching mockups
        self.dept_table = QTableWidget()
        self.dept_table.setColumnCount(3)
        self.dept_table.setHorizontalHeaderLabels(["DEPT", "EMP", "OK"])
        self.dept_table.verticalHeader().setVisible(False)
        self.dept_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.dept_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.dept_table.setShowGrid(False)
        self.dept_table.setFocusPolicy(Qt.NoFocus)
        self.dept_table.setStyleSheet("""
            QTableWidget {
                background-color: #ffffff;
                border: none;
                gridline-color: transparent;
            }
            QHeaderView::section {
                background-color: #f9fafb;
                color: #4b5563;
                font-weight: 800;
                font-size: 13px;
                padding: 10px 4px;
                border: none;
                border-bottom: 2px solid #e5e7eb;
                text-align: left;
            }
            QTableWidget::item {
                border-bottom: 1px solid #f3f4f6;
                padding-left: 8px;
                padding-right: 8px;
                color: #111827;
                font-size: 13px;
            }
            QTableWidget::item:selected {
                background-color: #f9fafb;
                color: #111827;
            }
        """)

        h_header = self.dept_table.horizontalHeader()
        h_header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        h_header.setSectionResizeMode(0, QHeaderView.Stretch)
        h_header.setSectionResizeMode(1, QHeaderView.Interactive)
        h_header.setSectionResizeMode(2, QHeaderView.Interactive)
        self.dept_table.setColumnWidth(1, 80)
        self.dept_table.setColumnWidth(2, 80)

        dept_layout.addWidget(self.dept_table)
        middle_grid.addWidget(dept_panel, 1)

        self._content_layout.addLayout(middle_grid)

        # 4. Bottom Row Action Boxes: Active Alarms, Cameras Online, Sync Status
        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(16)

        # 4a. Active Alarms Box
        self.alarm_box = QFrame()
        self.alarm_box.setStyleSheet("background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;")
        alarm_box_layout = QHBoxLayout(self.alarm_box)
        alarm_box_layout.setContentsMargins(16, 12, 16, 12)

        alarm_texts = QVBoxLayout()
        alarm_title = QLabel("Active Alarms")
        alarm_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #111827; border: none;")
        self.alarm_desc = QLabel("0 unknown persons")
        self.alarm_desc.setStyleSheet("font-size: 13px; color: #4b5563; border: none;")
        alarm_texts.addWidget(alarm_title)
        alarm_texts.addWidget(self.alarm_desc)
        alarm_box_layout.addLayout(alarm_texts)
        alarm_box_layout.addStretch()

        alarm_btn = QPushButton("View")
        alarm_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc2626;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #b91c1c;
            }
        """)
        alarm_box_layout.addWidget(alarm_btn)
        bottom_row.addWidget(self.alarm_box)

        # 4b. Cameras Online Box
        self.camera_box = QFrame()
        self.camera_box.setStyleSheet("background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;")
        camera_box_layout = QHBoxLayout(self.camera_box)
        camera_box_layout.setContentsMargins(16, 12, 16, 12)

        camera_texts = QVBoxLayout()
        camera_title = QLabel("Cameras Online")
        camera_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #111827; border: none;")
        self.camera_desc = QLabel("0 of 0 active")
        self.camera_desc.setStyleSheet("font-size: 13px; color: #4b5563; border: none;")
        camera_texts.addWidget(camera_title)
        camera_texts.addWidget(self.camera_desc)
        camera_box_layout.addLayout(camera_texts)
        camera_box_layout.addStretch()

        camera_btn = QPushButton("Manage")
        camera_btn.setStyleSheet("""
            QPushButton {
                background-color: #f3f4f6;
                color: #374151;
                font-size: 11px;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
                border: 1px solid #d1d5db;
            }
            QPushButton:hover {
                background-color: #e5e7eb;
            }
        """)
        camera_box_layout.addWidget(camera_btn)
        bottom_row.addWidget(self.camera_box)

        # 4c. Sync Status Box
        self.sync_box = QFrame()
        self.sync_box.setStyleSheet("background-color: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px;")
        sync_box_layout = QHBoxLayout(self.sync_box)
        sync_box_layout.setContentsMargins(16, 12, 16, 12)

        sync_texts = QVBoxLayout()
        sync_title = QLabel("Sync Status")
        sync_title.setStyleSheet("font-size: 13px; font-weight: 700; color: #111827; border: none;")
        self.sync_desc = QLabel("Pending cloud upload")
        self.sync_desc.setStyleSheet("font-size: 13px; color: #4b5563; border: none;")
        sync_texts.addWidget(sync_title)
        sync_texts.addWidget(self.sync_desc)
        # sync_box_layout.addLayout(sync_texts)
        sync_box_layout.addStretch()

        sync_btn = QPushButton("Sync Now")
        sync_btn.setStyleSheet("""
            QPushButton {
                background-color: #1a73e8;
                color: #ffffff;
                font-size: 11px;
                font-weight: bold;
                padding: 6px 14px;
                border-radius: 4px;
                border: none;
            }
            QPushButton:hover {
                background-color: #1557b0;
            }
        """)
        sync_box_layout.addWidget(sync_btn)
        # bottom_row.addWidget(self.sync_box)

        self._content_layout.addLayout(bottom_row)

        # Connect footer actions to window navigation if parent is available
        alarm_btn.clicked.connect(lambda: self._navigate_parent("alarms"))
        camera_btn.clicked.connect(lambda: self._navigate_parent("cameras"))
        sync_btn.clicked.connect(self._trigger_sync)

    def _navigate_parent(self, page_key: str):
        # Bubble up page change navigation to MainWindow
        parent = self.parentWidget()
        while parent:
            if hasattr(parent, "navigate_to"):
                parent.navigate_to(page_key)
                break
            parent = parent.parentWidget()

    def _trigger_sync(self):
        try:
            self.sync_desc.setText("Syncing operational overview...")
            self.db._store.run_sync()
            self.refresh()
            self.sync_desc.setText("Sync completed successfully")
        except Exception as e:
            self.sync_desc.setText(f"Sync failed: {e}")

    def refresh(self):
        # 1. Fetch live metrics with safety fallbacks
        try:
            stats = self.db.dashboard_stats()
        except Exception:
            stats = {}

        total_emp = stats.get("active_employees", 0)
        cams_active = stats.get("active_cameras", 0)

        try:
            all_cams = self.db.list_cameras()
            total_cams = len(all_cams)
        except Exception:
            all_cams = []
            total_cams = 0

        try:
            today_str = datetime.now().strftime("%Y-%m-%d")
            attendance_today = self.db.list_attendance(today_str)
            # Attendance records represent a present employee. Older records do
            # not have a status column, so treat a missing status as Present.
            checked_in_count = sum(
                1 for a in attendance_today
                if a.get("status", "Present") in ("Present", "Checked In", "Complete")
            )
        except Exception:
            attendance_today = []
            checked_in_count = 0

        att_rate = 0.0
        if total_emp > 0:
            att_rate = (checked_in_count / total_emp) * 100.0

        # Update cards
        self.card_employees.update_value(str(total_emp), f"{stats.get('departments', 0)} departments")
        self.card_attendance.update_value(f"{att_rate:.1f}%", f"{checked_in_count}/{total_emp} present today")

        try:
            alarm_events = self.db.list_alarm_events(100)
            active_alarms_count = len(alarm_events)
        except Exception:
            alarm_events = []
            active_alarms_count = 0

        self.card_alerts.update_value(str(active_alarms_count), f"{active_alarms_count} alerts pending")
        self.card_cameras.update_value(str(cams_active), f"{cams_active} of {total_cams} active")

        self.last_updated_lbl.setText(f"Updated {datetime.now().strftime('%I:%M:%S %p')}")

        self.alarm_desc.setText(f"{active_alarms_count} unknown alerts pending")
        inactive_names = [
            str(camera.get("name") or camera.get("id") or "Camera")
            for camera in all_cams
            if not camera.get("enabled")
        ]
        camera_text = f"{cams_active} of {total_cams} active"
        if inactive_names:
            camera_text += f" • Offline: {', '.join(inactive_names[:2])}"
        self.camera_desc.setText(camera_text)

        # 2. Render recent detections matching design mockups (list items with profile avatar placeholder)
        try:
            recent_records = self.db.recent_attendance(5)
        except Exception:
            recent_records = []

        # Clear old layouts
        while self.detections_list_layout.count():
            item = self.detections_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not recent_records:
            placeholder = QLabel("No recent activity records found")
            placeholder.setStyleSheet("color: #6b7280; font-size: 12px; font-weight: 500; border: none; padding: 12px;")
            self.detections_list_layout.addWidget(placeholder)
        else:
            for rec in recent_records:
                row_widget = QWidget()
                row_widget.setStyleSheet("border: none; background: transparent;")
                row_layout = QHBoxLayout(row_widget)
                row_layout.setContentsMargins(0, 6, 0, 6)

                # Circular visual Avatar representation
                avatar = QLabel()
                avatar.setFixedSize(36, 36)
                avatar.setAlignment(Qt.AlignCenter)
                avatar.setStyleSheet("""
                    background-color: #f3f4f6;
                    border-radius: 18px;
                    font-size: 16px;
                """)
                is_unknown = "unknown" in rec.get("label", "").lower() or rec.get("employee_id") is None
                # Double check to prevent naming conflict where a valid user name is checked as unknown
                if rec.get("label") and "unknown" not in rec.get("label", "").lower():
                    is_unknown = False

                avatar.setText("👤")
                row_layout.addWidget(avatar)

                # Info labels stack
                info_layout = QVBoxLayout()
                info_layout.setSpacing(2)

                name_lbl = QLabel(rec.get("label", "Unknown Person"))
                name_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #111827;")

                # Extract real employee code and camera identifiers from record
                emp_code_raw = rec.get("employee_code")
                # Fallback to checking label if code is missing but it's a known person
                if not emp_code_raw and not is_unknown:
                    emp_code_raw = "No code assigned"
                if len(str(emp_code_raw)) > 8: # If UUID format, abbreviate
                    emp_code_raw = str(emp_code_raw)[:8]

                cam_name_raw = rec.get("last_camera_name") or rec.get("camera_name") or "CAM-01"

                code_text = f"EMP-{emp_code_raw}" if not is_unknown else "Unknown"
                timestamp = rec.get("last_appearance") or rec.get("first_appearance")
                time_text = ""
                if timestamp:
                    try:
                        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        time_text = parsed.astimezone().strftime("%I:%M %p")
                    except (TypeError, ValueError, OverflowError):
                        pass
                code_cam = f"{code_text}  •  {cam_name_raw}"
                if time_text:
                    code_cam += f"  •  {time_text}"
                code_lbl = QLabel(code_cam)
                code_lbl.setStyleSheet("font-size: 13px; color: #4b5563; font-weight: 500;")

                info_layout.addWidget(name_lbl)
                info_layout.addWidget(code_lbl)
                row_layout.addLayout(info_layout)
                row_layout.addStretch()

                # Confidence
                conf = rec.get("max_confidence", 0.0)
                conf_lbl = QLabel(f"{conf * 100:.1f}%" if conf <= 1.0 else f"{conf:.1f}%")
                conf_lbl.setStyleSheet("font-size: 13px; font-weight: 700; color: #1a73e8; margin-right: 12px;")
                row_layout.addWidget(conf_lbl)

                # Pill Status
                status_pill = Pill("Unknown" if is_unknown else "Known", "error" if is_unknown else "success")
                row_layout.addWidget(status_pill)

                # Thin line separator
                line = QFrame()
                line.setFrameShape(QFrame.HLine)
                line.setFrameShadow(QFrame.Sunken)
                line.setStyleSheet("background-color: #f3f4f6; max-height: 1px; border: none;")

                self.detections_list_layout.addWidget(row_widget)
                self.detections_list_layout.addWidget(line)

        # 3. Render Department Attendance Table
        try:
            depts = self.db.list_departments()
            # If the database returns lists of real departments, calculate real ok_rate dynamically:
            today_str = datetime.now().strftime("%Y-%m-%d")
            try:
                attendance_today = self.db.list_attendance(today_str)
            except Exception:
                attendance_today = []

            # Attendance rows may have been recorded before a camera was
            # assigned to a department, so do not depend only on the row's
            # department columns. Resolve the recognized employee back to
            # their current department membership.
            try:
                employees = self.db.list_employees()
            except Exception:
                employees = []
            employee_departments = {}
            for employee in employees:
                identity_keys = {
                    str(employee.get("name") or "").strip().casefold(),
                    str(employee.get("employee_code") or "").strip().casefold(),
                }
                identity_keys.discard("")
                for key in identity_keys:
                    employee_departments[key] = employee.get("departments") or []

            for dept in depts:
                dept_id = dept.get("id")
                # Calculate real ok_rate based on today's attendance logs
                dept_emps_count = dept.get("employee_count", 0)
                if dept_emps_count > 0:
                    present_in_dept = sum(
                        1 for a in attendance_today
                        if (
                            str(a.get("last_department_id") or a.get("first_department_id") or "") == str(dept_id)
                            or str(dept_id) in {
                                str(value) for value in employee_departments.get(
                                    str(a.get("employee_code") or a.get("label") or "").strip().casefold(), []
                                )
                            }
                        )
                        and a.get("status", "Present") in ("Present", "Checked In", "Complete")
                    )
                    dept["ok_rate"] = (present_in_dept / dept_emps_count) * 100.0
                else:
                    dept["ok_rate"] = 0.0

            # If the database is empty, fallback to the design mockups
            if not depts:
                depts = []
        except Exception:
            depts = []

        self.dept_table.setRowCount(len(depts))
        for row_idx, dept in enumerate(depts):
            self.dept_table.setRowHeight(row_idx, 40)

            # DEPT Name
            dept_item = QTableWidgetItem(dept.get("name", "General"))
            font = QFont()
            font.setBold(True)
            dept_item.setFont(font)
            dept_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.dept_table.setItem(row_idx, 0, dept_item)

            # EMP counts
            emp_count = dept.get("employee_count", 0)
            emp_item = QTableWidgetItem(str(emp_count))
            emp_item.setTextAlignment(Qt.AlignCenter)
            self.dept_table.setItem(row_idx, 1, emp_item)

            # Attendance OK Pill Widget
            ok_rate = dept.get("ok_rate", 88.0)

            ok_widget = QWidget()
            ok_lay = QHBoxLayout(ok_widget)
            ok_lay.setContentsMargins(0, 0, 0, 0)
            ok_lay.setAlignment(Qt.AlignCenter)
            ok_badge = Pill(f"{int(ok_rate)}%", "success")
            ok_badge.setFixedWidth(54)
            ok_lay.addWidget(ok_badge)
            self.dept_table.setCellWidget(row_idx, 2, ok_widget)
