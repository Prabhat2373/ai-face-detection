"""Dashboard page with overview stats for the FaceAgent app."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout,
    QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ..widgets import StatCard, SectionHeader, Pill
from ..database import Database


class DashboardPage(QWidget):
    """Main dashboard with stats cards and recent activity."""

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
        title = QLabel("Dashboard")
        title.setProperty("class", "page-title")
        desc = QLabel("Real-time overview of your face detection system")
        desc.setProperty("class", "page-desc")
        header_layout.addWidget(title)
        header_layout.addWidget(desc)
        self._main_layout.addWidget(header)

        # Stats row
        self._stats_layout = QHBoxLayout()
        self._stats_layout.setSpacing(12)
        self._stat_cameras = StatCard("Active Cameras", "0")
        self._stat_employees = StatCard("Active Employees", "0")
        self._stat_departments = StatCard("Departments", "0")
        self._stat_faces = StatCard("Known Faces", "0")
        self._stat_attendance = StatCard("Attendance Records", "0")

        for card in [self._stat_cameras, self._stat_employees, self._stat_departments,
                     self._stat_faces, self._stat_attendance]:
            self._stats_layout.addWidget(card)
        self._main_layout.addLayout(self._stats_layout)

        # Recent attendance
        self._main_layout.addWidget(SectionHeader("Recent Attendance", "Latest check-ins and check-outs"))
        self._attendance_table = QTableWidget()
        self._attendance_table.setColumnCount(5)
        self._attendance_table.setHorizontalHeaderLabels(
            ["Name", "First Seen", "Last Seen", "Appearances", "Max Confidence"]
        )
        self._attendance_table.horizontalHeader().setStretchLastSection(True)
        self._attendance_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._attendance_table.setSelectionBehavior(QTableWidget.SelectRows)
        self._attendance_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._attendance_table.setAlternatingRowColors(True)
        self._attendance_table.setStyleSheet("""
            QTableWidget { alternate-background-color: rgba(155, 173, 200, 0.03); }
        """)
        self._attendance_table.setMinimumHeight(200)
        self._main_layout.addWidget(self._attendance_table)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        stats = self.db.dashboard_stats()
        self._stat_cameras.set_value(str(stats["active_cameras"]))
        self._stat_employees.set_value(str(stats["active_employees"]))
        self._stat_departments.set_value(str(stats["departments"]))
        self._stat_faces.set_value(str(stats["known_faces"]))
        self._stat_attendance.set_value(str(stats["total_attendance"]))

        records = self.db.recent_attendance(50)
        self._attendance_table.setRowCount(len(records))
        for row_idx, rec in enumerate(records):
            self._attendance_table.setItem(row_idx, 0, QTableWidgetItem(rec.get("label", "")))
            first = rec.get("first_appearance", "")
            if first:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(first.replace("Z", "+00:00"))
                    first = dt.strftime("%b %d, %Y %H:%M")
                except Exception:
                    pass
            self._attendance_table.setItem(row_idx, 1, QTableWidgetItem(first))

            last = rec.get("last_appearance", "")
            if last:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                    last = dt.strftime("%b %d, %Y %H:%M")
                except Exception:
                    pass
            self._attendance_table.setItem(row_idx, 2, QTableWidgetItem(last))
            self._attendance_table.setItem(row_idx, 3, QTableWidgetItem(str(rec.get("appearances", 0))))
            conf = rec.get("max_confidence", 0)
            self._attendance_table.setItem(row_idx, 4, QTableWidgetItem(f"{conf:.2f}" if isinstance(conf, (int, float)) else str(conf)))
