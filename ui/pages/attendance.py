#!/usr/bin/env python3
"""Attendance page for viewing and managing attendance records.

This page shows:
 - KPI stat cards
 - Date selector (calendar popup forced to light styling)
 - Department and Status filters (popup list views forced to light styling)
 - Search box
 - Export / Refresh buttons
 - Single attendance table with merged rows (employees + attendance) showing absentees
"""

from datetime import date, datetime

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QLineEdit, QMessageBox, QDateEdit, QComboBox, QListView,
)
from PySide6.QtCore import QDate, QSize, Qt
from PySide6.QtGui import QColor, QBrush

from ..widgets import StatCard
from ..database import Database
from ..backend_process import writable_app_dir


class AttendancePage(QWidget):
    """Attendance records page with KPI cards, filters and the attendance table."""

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
        layout.setSpacing(16)

        # Page header
        header = QWidget()
        hdr_layout = QHBoxLayout(header)
        hdr_layout.setContentsMargins(0, 0, 0, 0)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        title = QLabel("Attendance Records")
        title.setProperty("class", "page-title")
        desc = QLabel("Date-wise attendance. Use filters to refine the list and export if needed.")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()

        # KPI cards
        kpi_container = QWidget()
        kpi_layout = QHBoxLayout(kpi_container)
        kpi_layout.setSpacing(12)
        self._stat_total = StatCard("Total Employees", "0")
        self._stat_checked = StatCard("Checked In Today", "0")
        self._stat_alarms = StatCard("Active Alarms", "0")
        self._stat_cameras = StatCard("Cameras Online", "0")
        for card in [self._stat_total, self._stat_checked, self._stat_alarms, self._stat_cameras]:
            kpi_layout.addWidget(card)

        # Combine header + KPIs in a real widget so popups anchor correctly
        header_container = QWidget()
        header_container_layout = QVBoxLayout(header_container)
        header_container_layout.setContentsMargins(0, 0, 0, 0)
        header_container_layout.setSpacing(8)
        header_container_layout.addWidget(header)
        header_container_layout.addWidget(kpi_container)
        layout.addWidget(header_container)

        # Filters / actions row
        filters = QWidget()
        f_layout = QHBoxLayout(filters)
        f_layout.setContentsMargins(0, 0, 0, 0)
        f_layout.setSpacing(8)

        # Date selector
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        self.date_input.setDisplayFormat("dd MMM yyyy")
        self.date_input.setMinimumWidth(160)
        self.date_input.setButtonSymbols(QDateEdit.UpDownArrows)
        self.date_input.dateChanged.connect(self.refresh)
        f_layout.addWidget(self.date_input)

        # Make the calendar popup use the app's light styling (avoid transparent/system theme)
        try:
            cal = self.date_input.calendarWidget()
            if cal is not None:
                cal.setAutoFillBackground(True)
                # apply a concise light stylesheet for the calendar popup
                cal.setStyleSheet(
                    "QCalendarWidget { background: #ffffff; color: #111827; selection-background-color: #e8f0fe; selection-color: #ffffff; }"
                    "QCalendarWidget QToolButton { background: #f8fafc; color: #111827; border: 1px solid #e5e7eb; }"
                    "QCalendarWidget QAbstractItemView { background: #ffffff; color: #111827; selection-background-color: #e8f0fe; selection-color: #ffffff; }"
                    "QCalendarWidget QMenu { background: #ffffff; color: #111827; }"
                )
        except Exception:
            # calendar might not be available in very old PySide builds; ignore
            pass

        # Department filter (use a styled QListView for consistent popup visuals)
        self.dept_filter = QComboBox()
        self.dept_filter.setMinimumWidth(160)
        self.dept_filter.currentIndexChanged.connect(self._apply_filters)
        try:
            self.dept_filter.setView(QListView())
            view = self.dept_filter.view()
            if view is not None:
                view.setStyleSheet(
                    "background:#ffffff; color:#111827; selection-background-color:#e8f0fe; selection-color:#ffffff;"
                )
        except Exception:
            pass
        f_layout.addWidget(self.dept_filter)

        # Status filter (styled popup list)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All Status", "Present", "Complete", "Checked In", "Absent"])
        self.status_filter.setMinimumWidth(140)
        self.status_filter.currentIndexChanged.connect(self._apply_filters)
        try:
            self.status_filter.setView(QListView())
            view2 = self.status_filter.view()
            if view2 is not None:
                view2.setStyleSheet(
                    "background:#ffffff; color:#111827; selection-background-color:#e8f0fe; selection-color:#ffffff;"
                )
        except Exception:
            pass
        f_layout.addWidget(self.status_filter)

        # Search box
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search employee...")
        self.search_input.setMinimumWidth(220)
        self.search_input.textChanged.connect(self._apply_filters)
        f_layout.addWidget(self.search_input)

        f_layout.addStretch()

        # Export & Refresh
        self.export_btn = QPushButton("Export")
        self.export_btn.setProperty("class", "primary")
        self.export_btn.setMinimumWidth(100)
        self.export_btn.clicked.connect(self._export_csv)
        f_layout.addWidget(self.export_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setMinimumWidth(100)
        self.refresh_btn.clicked.connect(self.refresh)
        f_layout.addWidget(self.refresh_btn)

        layout.addWidget(filters)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels(
            ["#", "Employee", "Department", "Check-In", "Check-Out", "Camera", "Status", "Conf"]
        )
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # #
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)  # Employee
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)  # Dept
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Check-In
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Check-Out
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Camera
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Status
        header_view.setSectionResizeMode(7, QHeaderView.ResizeToContents)  # Conf
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setSortingEnabled(True)
        self._table.setIconSize(QSize(40, 40))
        self._table.setMinimumHeight(360)
        layout.addWidget(self._table)

        # Footer
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self._count_label = QLabel("0 records")
        self._count_label.setProperty("class", "muted")
        footer_layout.addWidget(self._count_label)
        footer_layout.addStretch()
        layout.addWidget(footer)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        """Reload data (KPIs, filters, table) for the selected date."""
        sel_date = self.date_input.date().toString("yyyy-MM-dd")

        employees = self.db.list_employees()
        cameras = self.db.list_cameras()
        attendance_all = self.db.list_attendance(sel_date)

        # KPIs
        total_emps = len(employees)
        checked_today = len(attendance_all)
        try:
            alarms = len(self.db.list_sync_events(100))
        except Exception:
            alarms = 0
        cameras_online = sum(1 for c in cameras if c.get("enabled"))
        total_cameras = len(cameras)

        self._stat_total.set_value(str(total_emps))
        # show departments as unit
        try:
            self._stat_total.set_unit(f"{len(self.db.list_departments())} departments")
        except Exception:
            pass
        self._stat_checked.set_value(str(checked_today))
        self._stat_alarms.set_value(str(alarms))
        self._stat_cameras.set_value(f"{cameras_online}/{total_cameras}")

        # populate department filter
        depts = [{"id": None, "name": "All Departments"}] + self.db.list_departments()
        self._departments = depts
        self.dept_filter.blockSignals(True)
        self.dept_filter.clear()
        for d in depts:
            self.dept_filter.addItem(d.get("name") or "Unknown", d.get("id"))
        self.dept_filter.setCurrentIndex(0)
        self.dept_filter.blockSignals(False)

        # build lookup of employees by name
        emp_by_label = {}
        for emp in employees:
            name = emp.get("name") or ""
            emp_by_label[name] = emp

        # merged rows: first include attendance records (present and unknowns)
        merged = []
        seen = set()
        for rec in attendance_all:
            lbl = rec.get("label") or ""
            seen.add(lbl)
            emp = emp_by_label.get(lbl)
            merged.append(self._build_row_from(rec, emp))

        # include absentees
        for emp in employees:
            name = emp.get("name") or ""
            if name in seen:
                continue
            absent_rec = {
                "label": name,
                "employee": emp,
                "first_appearance": None,
                "last_appearance": None,
                "first_camera_name": None,
                "last_camera_name": None,
                "appearances": 0,
                "max_confidence": None,
                "first_camera_role": None,
                "last_camera_role": None,
            }
            merged.append(self._build_row_from(absent_rec, emp))

        self._all_rows = merged
        self._apply_filters()

    def _build_row_from(self, rec: dict, emp: dict | None):
        """Normalize a record (attendance or absent placeholder) into the table row shape."""
        label = rec.get("label") or (emp.get("name") if emp else "Unknown")
        emp_code = emp.get("employee_code") if emp else ""
        dept_name = emp.get("department_name") if emp else (rec.get("last_department_name") or rec.get("first_department_name") or "")
        first = rec.get("first_appearance") or rec.get("first")
        last = rec.get("last_appearance") or rec.get("last")
        camera = rec.get("last_camera_name") or rec.get("first_camera_name") or rec.get("last_camera_id") or rec.get("first_camera_id") or "-"
        appearances = rec.get("appearances", 0)
        max_conf = rec.get("max_confidence")

        if first and last and first != last:
            status = "Complete"
        elif first and not last:
            status = "Checked In"
        elif first and last and first == last:
            status = "Checked In"
        else:
            status = "Absent"

        return {
            "label": label,
            "employee": emp,
            "employee_code": emp_code or "",
            "department": dept_name or "",
            "first": first,
            "last": last,
            "camera": camera,
            "appearances": appearances,
            "max_confidence": max_conf,
            "status": status,
            "present": status != "Absent",
        }

    def _apply_filters(self):
        rows = list(self._all_rows) if hasattr(self, "_all_rows") else []

        # department filter (match id or name)
        dept_id = self.dept_filter.currentData()
        if dept_id:
            def dept_match(r):
                emp = r.get("employee") or {}
                if isinstance(emp, dict):
                    if emp.get("department_id") == dept_id:
                        return True
                    if str(emp.get("department_name") or "").lower() == str(self.dept_filter.currentText() or "").lower():
                        return True
                return (r.get("department") or "").lower() == (self.dept_filter.currentText() or "").lower()
            rows = [r for r in rows if dept_match(r)]

        # status filter
        status = self.status_filter.currentText()
        if status and status != "All Status":
            rows = [r for r in rows if r.get("status") == status or (status == "Present" and r.get("present"))]

        # search
        text = self.search_input.text().strip().lower()
        if text:
            def matches(r):
                if text in (r.get("label") or "").lower():
                    return True
                if text in (r.get("employee_code") or "").lower():
                    return True
                if text in (r.get("department") or "").lower():
                    return True
                return False
            rows = [r for r in rows if matches(r)]

        # sort: present first then label
        rows.sort(key=lambda x: (not x.get("present"), x.get("label", "").lower()))
        self._populate_table(rows)

    def _populate_table(self, records):
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))
        self._table.verticalHeader().setDefaultSectionSize(56)

        for idx, rec in enumerate(records, start=1):
            row_idx = idx - 1
            # index
            item_idx = QTableWidgetItem(str(idx))
            item_idx.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row_idx, 0, item_idx)

            # employee (name + code)
            name = rec.get("label") or ""
            code = rec.get("employee_code") or ""
            emp_text = name + (f"\n{code}" if code else "")
            self._table.setItem(row_idx, 1, QTableWidgetItem(emp_text))

            # department
            dept = rec.get("department") or ""
            self._table.setItem(row_idx, 2, QTableWidgetItem(dept))

            # check-in / check-out
            first = rec.get("first")
            last = rec.get("last")
            self._table.setItem(row_idx, 3, QTableWidgetItem(self._format_dt(first)))
            self._table.setItem(row_idx, 4, QTableWidgetItem(self._format_dt(last)))

            # camera
            cam = rec.get("camera") or "-"
            self._table.setItem(row_idx, 5, QTableWidgetItem(cam))

            # status with light color hints
            status = rec.get("status") or ""
            item_status = QTableWidgetItem(status)
            if status == "Complete":
                item_status.setBackground(QBrush(QColor(220, 249, 231)))
                item_status.setForeground(QBrush(QColor(0, 120, 60)))
            elif status == "Checked In":
                item_status.setBackground(QBrush(QColor(237, 246, 255)))
                item_status.setForeground(QBrush(QColor(8, 70, 140)))
            elif status == "Absent":
                item_status.setBackground(QBrush(QColor(255, 237, 237)))
                item_status.setForeground(QBrush(QColor(160, 40, 40)))
            self._table.setItem(row_idx, 6, item_status)

            # confidence
            conf = rec.get("max_confidence")
            conf_text = "-" if conf is None else (f"{conf:.1f}%" if isinstance(conf, (int, float)) else str(conf))
            item_conf = QTableWidgetItem(conf_text)
            item_conf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row_idx, 7, item_conf)

        self._table.setSortingEnabled(True)
        self._count_label.setText(f"{len(records)} records")

    def _format_dt(self, iso_str):
        if not iso_str:
            return "-"
        try:
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return dt.strftime("%H:%M:%S")
        except Exception:
            return iso_str

    def _export_csv(self):
        """Export visible rows to CSV for the selected date."""
        try:
            sel_date = self.date_input.date().toString("yyyy-MM-dd")
            export_dir = writable_app_dir() / "exports"
            export_dir.mkdir(parents=True, exist_ok=True)
            path = export_dir / f"attendance-{sel_date}.csv"
            import csv
            rows = []
            for r in range(self._table.rowCount()):
                rows.append({
                    "index": self._table.item(r, 0).text() if self._table.item(r, 0) else "",
                    "name": self._table.item(r, 1).text() if self._table.item(r, 1) else "",
                    "department": self._table.item(r, 2).text() if self._table.item(r, 2) else "",
                    "first": self._table.item(r, 3).text() if self._table.item(r, 3) else "",
                    "last": self._table.item(r, 4).text() if self._table.item(r, 4) else "",
                    "camera": self._table.item(r, 5).text() if self._table.item(r, 5) else "",
                    "status": self._table.item(r, 6).text() if self._table.item(r, 6) else "",
                    "confidence": self._table.item(r, 7).text() if self._table.item(r, 7) else "",
                })
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Index", "Name", "Department", "Check-In", "Check-Out", "Camera", "Status", "Confidence"])
                for r in rows:
                    writer.writerow([r["index"], r["name"], r["department"], r["first"], r["last"], r["camera"], r["status"], r["confidence"]])
            QMessageBox.information(self, "Export Complete", f"Attendance exported to\n{path}")
        except Exception as e:
            QMessageBox.warning(self, "Export Error", str(e))
