"""Attendance page for viewing and managing attendance records."""

from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QLineEdit, QMessageBox, QDateEdit,
)
from PySide6.QtCore import QDate, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap

from ..widgets import SectionHeader
from ..database import Database
from ..backend_process import writable_app_dir


class AttendancePage(QWidget):
    """Attendance records page with table view and actions."""

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
        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header
        header = QWidget()
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(0, 0, 0, 0)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        title = QLabel("Attendance Records")
        title.setProperty("class", "page-title")
        desc = QLabel("View and export check-in / check-out history")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()

        # Actions
        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setDisplayFormat("dd MMM yyyy")
        self.date_input.setMinimumWidth(150)
        self.date_input.setButtonSymbols(QDateEdit.UpDownArrows)
        self.date_input.dateChanged.connect(self.refresh)
        actions.addWidget(self.date_input)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name...")
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._filter_table)
        actions.addWidget(self.search_input)

        self.export_btn = QPushButton("Export CSV")
        self.export_btn.setProperty("class", "primary")
        self.export_btn.setMinimumWidth(110)
        self.export_btn.clicked.connect(self._export_csv)
        actions.addWidget(self.export_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setMinimumWidth(90)
        self.refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_btn)

        hdr_layout.addLayout(actions)
        layout.addWidget(header)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Snapshot", "Name", "First Appearance", "Last Appearance",
            "Appearances", "Max Confidence", "First Role", "Last Role"
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for column in range(1, 8):
            header_view.setSectionResizeMode(column, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        layout.addWidget(self._table)

        # Footer stats
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self._count_label = QLabel("0 records")
        self._count_label.setStyleSheet("color: #6b7d9a; font-size: 12px;")
        footer_layout.addWidget(self._count_label)
        footer_layout.addStretch()
        layout.addWidget(footer)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        selected_date = self.date_input.date().toString("yyyy-MM-dd")
        self._records = self.db.list_attendance(selected_date)
        self._populate_table(self._records)

    def _populate_table(self, records):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))
        self._table.setIconSize(QSize(64, 42))
        self._table.verticalHeader().setDefaultSectionSize(54)

        for row_idx, rec in enumerate(records):
            snapshot_path = rec.get("last_snapshot_path") or rec.get("first_snapshot_path")
            snapshot_label = QLabel()
            snapshot_label.setAlignment(Qt.AlignCenter)
            if snapshot_path:
                pixmap = QPixmap(str(snapshot_path))
                if not pixmap.isNull():
                    snapshot_label.setPixmap(pixmap.scaled(64, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    snapshot_label.setText("No image")
            else:
                snapshot_label.setText("-")
            self._table.setCellWidget(row_idx, 0, snapshot_label)

            self._table.setItem(row_idx, 1, QTableWidgetItem(rec.get("label", "")))

            first = rec.get("first_appearance", "")
            self._table.setItem(row_idx, 2, QTableWidgetItem(self._format_date(first)))

            last = rec.get("last_appearance", "")
            self._table.setItem(row_idx, 3, QTableWidgetItem(self._format_date(last)))

            self._table.setItem(row_idx, 4, QTableWidgetItem(str(rec.get("appearances", 0))))

            conf = rec.get("max_confidence", 0)
            self._table.setItem(row_idx, 5, QTableWidgetItem(
                f"{conf:.2f}" if isinstance(conf, (int, float)) else str(conf)
            ))

            self._table.setItem(row_idx, 6, QTableWidgetItem(rec.get("first_camera_role", "-")))
            self._table.setItem(row_idx, 7, QTableWidgetItem(rec.get("last_camera_role", "-")))

        self._table.setSortingEnabled(True)
        self._count_label.setText(f"{len(records)} records")

    def _format_date(self, date_str):
        if not date_str:
            return "-"
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            return dt.strftime("%b %d, %Y  %H:%M")
        except Exception:
            return date_str

    def _filter_table(self, text):
        if not hasattr(self, '_records'):
            return
        if not text.strip():
            self._populate_table(self._records)
            return
        filtered = [
            r for r in self._records
            if text.lower() in r.get("label", "").lower()
        ]
        self._populate_table(filtered)

    def _export_csv(self):
        export_dir = writable_app_dir() / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"attendance-{date.today().isoformat()}.csv"
        try:
            records = self.db.list_attendance()
            import csv
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "Name", "Date", "First Appearance", "Last Appearance",
                    "Appearances", "Max Confidence", "First Role", "Last Role"
                ])
                for rec in records:
                    writer.writerow([
                        rec.get("label", ""),
                        rec.get("attendance_date", ""),
                        rec.get("first_appearance", ""),
                        rec.get("last_appearance", ""),
                        rec.get("appearances", 0),
                        rec.get("max_confidence", 0),
                        rec.get("first_camera_role", ""),
                        rec.get("last_camera_role", ""),
                    ])
            QMessageBox.information(self, "Export Complete",
                f"Attendance records exported to:\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))
