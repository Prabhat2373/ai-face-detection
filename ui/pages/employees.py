"""Employees page for managing employee records and face registration."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QLineEdit, QComboBox, QMessageBox,
    QDialog, QFormLayout, QDialogButtonBox, QCheckBox,
    QToolButton, QMenu, QAbstractItemView, QStyledItemDelegate,
    QFileDialog, QGridLayout,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from typing import Optional

from ..widgets import SectionHeader, EmptyState
from ..database import Database
from ..backend_client import BackendClient


class EmployeeDialog(QDialog):
    """Dialog for adding / editing an employee."""

    def __init__(self, employee: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.employee = employee
        self.db = Database.get()
        self.backend = BackendClient()
        self._selected_photo_paths: list[str] = []
        self._selected_photo_pixmaps: list[QPixmap] = []
        self.setWindowTitle("Edit Employee" if employee else "Add Employee")
        self.setMinimumWidth(560)
        self.setModal(True)
        self._build_ui()
        if employee:
            self._populate(employee)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        self.setStyleSheet("""
            QDialog {
                background: #f4f6fb;
                color: #111827;
            }
            QLabel {
                color: #111827;
            }
            QLineEdit, QComboBox, QCheckBox, QDialogButtonBox QPushButton {
                color: #111827;
            }
            QLineEdit, QComboBox {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 7px;
                padding: 10px 13px;
                min-height: 22px;
            }
            QLineEdit:focus, QComboBox:focus {
                border-color: #1a73e8;
            }
            QDialogButtonBox QPushButton {
                background: #f8fafc;
                border: 1px solid #e5e7eb;
                border-radius: 7px;
                padding: 9px 16px;
                font-weight: 700;
            }
            QDialogButtonBox QPushButton:hover {
                border-color: #1a73e8;
            }
        """)

        title = QLabel("Edit Employee" if self.employee else "New Employee")
        title.setProperty("class", "page-title")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignRight)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("John Doe")
        form.addRow("Name", self._name_input)

        self._code_input = QLineEdit()
        self._code_input.setPlaceholderText("EMP-001")
        form.addRow("Employee Code", self._code_input)

        self._role_input = QLineEdit()
        self._role_input.setPlaceholderText("Developer")
        form.addRow("Role", self._role_input)

        self._dept_combo = QComboBox()
        self._dept_combo.addItem("No department", "")
        for dept in self.db.list_departments():
            self._dept_combo.addItem(dept["name"], dept["id"])
        form.addRow("Department", self._dept_combo)

        self._active_check = QCheckBox("Active")
        self._active_check.setChecked(True)
        form.addRow("Status", self._active_check)

        photo_row = QHBoxLayout()
        self._photos_label = QLabel("No photos selected")
        self._photos_label.setProperty("class", "muted")
        self._photos_btn = QPushButton("Choose Photos")
        self._photos_btn.clicked.connect(self._choose_photos)
        photo_row.addWidget(self._photos_label, 1)
        photo_row.addWidget(self._photos_btn)
        form.addRow("Photos", photo_row)

        layout.addLayout(form)

        self._photo_preview = QWidget()
        self._photo_preview.setMinimumHeight(96)
        preview_layout = QGridLayout(self._photo_preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)
        self._preview_layout = preview_layout
        layout.addWidget(self._photo_preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, employee: dict):
        self._name_input.setText(employee.get("name", ""))
        self._code_input.setText(employee.get("employee_code", ""))
        self._role_input.setText(employee.get("role", ""))
        idx = self._dept_combo.findData(employee.get("department_id"))
        if idx >= 0:
            self._dept_combo.setCurrentIndex(idx)
        self._active_check.setChecked(bool(employee.get("active")))
        photo_count = int(employee.get("photoCount") or 0)
        self._photos_label.setText(f"{photo_count} existing photos" if photo_count else "No existing photos")
        self._render_photo_previews([])
        if photo_count:
            existing = QLabel(f"Existing face samples: {photo_count}")
            existing.setProperty("class", "muted")
            self._preview_layout.addWidget(existing, 1, 0, 1, 6)

    def _choose_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select employee photos",
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp);;All Files (*)",
        )
        if not paths:
            return
        self._selected_photo_paths = paths
        self._photos_label.setText(f"{len(paths)} photo(s) selected")
        self._render_photo_previews(paths)

    def _render_photo_previews(self, paths: list[str]):
        while self._preview_layout.count():
            item = self._preview_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        if not paths:
            hint = QLabel("Selected photos will appear here")
            hint.setProperty("class", "muted")
            hint.setAlignment(Qt.AlignCenter)
            hint.setStyleSheet("padding: 18px; border: 1px dashed #cbd5e1; border-radius: 8px; background: #ffffff;")
            self._preview_layout.addWidget(hint, 0, 0, 1, 6)
            return
        for idx, path in enumerate(paths[:6]):
            lbl = QLabel()
            lbl.setFixedSize(76, 76)
            lbl.setStyleSheet("border: 1px solid #e5e7eb; border-radius: 8px; background: #ffffff;")
            pix = QPixmap(path)
            if not pix.isNull():
                lbl.setPixmap(pix.scaled(76, 76, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
                lbl.setScaledContents(True)
            else:
                lbl.setText("No preview")
                lbl.setAlignment(Qt.AlignCenter)
            self._preview_layout.addWidget(lbl, idx // 6, idx % 6)

    def get_data(self) -> dict:
        return {
            "id": self.employee.get("id") if self.employee else None,
            "name": self._name_input.text().strip(),
            "employee_code": self._code_input.text().strip(),
            "role": self._role_input.text().strip(),
            "department_id": self._dept_combo.currentData() or None,
            "active": self._active_check.isChecked(),
            "photos": list(self._selected_photo_paths),
        }


class EmployeesPage(QWidget):
    """Employees management page with table and add/edit/delete."""

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
        title = QLabel("Employees")
        title.setProperty("class", "page-title")
        desc = QLabel("Manage employees and their face profiles")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search employees...")
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._filter_table)
        actions.addWidget(self.search_input)

        self.add_btn = QPushButton("+ Add Employee")
        self.add_btn.setProperty("class", "primary")
        self.add_btn.setStyleSheet("""
            QPushButton {
                background: #1a73e8;
                color: #ffffff;
                border: 1px solid #1a73e8;
                border-radius: 7px;
                padding: 9px 16px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #1765cc;
                border-color: #1765cc;
            }
        """)
        self.add_btn.clicked.connect(self._add_employee)
        actions.addWidget(self.add_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_btn)

        hdr_layout.addLayout(actions)
        layout.addWidget(header)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "Name", "Code", "Role", "Department", "Status", "Action", "ID"
        ])
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.Stretch)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget { alternate-background-color: rgba(155, 173, 200, 0.03); }
            QToolButton {
                padding: 5px 10px;
                border-radius: 6px;
                background: #ffffff;
                color: #111827;
                border: 1px solid #e5e7eb;
                min-width: 56px;
                min-height: 28px;
            }
            QToolButton:hover {
                border-color: #1a73e8;
            }
            QToolButton[class="danger"] {
                color: #dc2626;
                border-color: rgba(220, 38, 38, 0.25);
            }
        """)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(54)
        self._table.setColumnHidden(6, True)  # Hide ID column
        layout.addWidget(self._table)

        # Count
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self._count_label = QLabel("0 employees")
        self._count_label.setProperty("class", "muted")
        footer_layout.addWidget(self._count_label)
        footer_layout.addStretch()
        layout.addWidget(footer)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        self._employees = self.db.list_employees()
        self._populate_table(self._employees)

    def _populate_table(self, employees):
        self._table.setRowCount(len(employees))
        for row_idx, emp in enumerate(employees):
            self._table.setRowHeight(row_idx, 54)
            self._table.setItem(row_idx, 0, QTableWidgetItem(emp.get("name", "")))
            self._table.setItem(row_idx, 1, QTableWidgetItem(emp.get("employee_code", "")))
            self._table.setItem(row_idx, 2, QTableWidgetItem(emp.get("role", "")))
            self._table.setItem(row_idx, 3, QTableWidgetItem(emp.get("department_name", "-")))
            status = "Active" if emp.get("active") else "Inactive"
            item = QTableWidgetItem(status)
            item.setForeground(Qt.green if emp.get("active") else Qt.gray)
            self._table.setItem(row_idx, 4, item)
            self._table.setCellWidget(row_idx, 5, self._build_action_widget(emp))
            self._table.setItem(row_idx, 6, QTableWidgetItem(emp.get("id", "")))

        self._count_label.setText(f"{len(employees)} employees")

    def _filter_table(self, text):
        if not hasattr(self, '_employees'):
            return
        if not text.strip():
            self._populate_table(self._employees)
            return
        filtered = [
            e for e in self._employees
            if text.lower() in e.get("name", "").lower()
            or text.lower() in e.get("employee_code", "").lower()
        ]
        self._populate_table(filtered)

    def _persist_employee(self, data: dict):
        photos = data.pop("photos", [])
        if not photos:
            raise ValueError("Please select at least one employee photo.")

        saved = self.db.save_employee(data)
        employee_id = saved.get("id") or data.get("id")
        if photos and employee_id:
            import base64
            payload = []
            for path in photos:
                with open(path, "rb") as f:
                    payload.append(base64.b64encode(f.read()).decode("utf-8"))
            self.backend.upload_employee_photos(employee_id, payload)
        return saved

    def _add_employee(self):
        dialog = EmployeeDialog(parent=self)
        if dialog.exec():
            data = dialog.get_data()
            try:
                self._persist_employee(data)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not save employee: {e}")

    def _employee_by_row(self, row: int) -> Optional[dict]:
        if row < 0 or row >= self._table.rowCount():
            return None
        id_item = self._table.item(row, 6)
        emp_id = id_item.text() if id_item else ""
        return next((e for e in getattr(self, "_employees", []) if e["id"] == emp_id), None)

    def _build_action_widget(self, employee: dict) -> QWidget:
        widget = QWidget()
        widget.setMinimumHeight(42)
        widget.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(14)

        edit_btn = QPushButton("Edit")
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setStyleSheet("""
            QPushButton {
                background: #ffffff;
                color: #1a73e8;
                border: 1px solid #cfe0ff;
                border-radius: 6px;
                padding: 5px 16px;
                font-weight: 700;
                min-width: 66px;
            }
            QPushButton:hover {
                background: #eef4ff;
                border-color: #1a73e8;
            }
        """)
        edit_btn.clicked.connect(lambda _checked=False, emp=employee: self._edit_employee(emp))
        layout.addWidget(edit_btn)

        delete_btn = QPushButton("Delete")
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.setStyleSheet("""
            QPushButton {
                background: #ffffff;
                color: #dc2626;
                border: 1px solid rgba(220, 38, 38, 0.28);
                border-radius: 6px;
                padding: 5px 16px;
                font-weight: 700;
                min-width: 66px;
            }
            QPushButton:hover {
                background: rgba(220, 38, 38, 0.08);
                border-color: #dc2626;
            }
        """)
        delete_btn.clicked.connect(lambda _checked=False, emp=employee: self._delete_employee(emp))
        layout.addWidget(delete_btn)

        layout.addStretch()
        return widget

    def _edit_employee(self, employee: dict):
        dialog = EmployeeDialog(employee, self)
        if dialog.exec():
            data = dialog.get_data()
            try:
                self._persist_employee(data)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not update employee: {e}")

    def _edit_selected(self):
        employee = self._employee_by_row(self._table.currentRow())
        if employee:
            self._edit_employee(employee)

    def _delete_employee(self, employee: dict):
        reply_box = QMessageBox(self)
        reply_box.setWindowTitle("Delete Employee")
        reply_box.setText(f"Are you sure you want to delete {employee.get('name', 'this employee')}?")
        reply_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        reply_box.setDefaultButton(QMessageBox.No)
        reply_box.setIcon(QMessageBox.Question)
        reply_box.setStyleSheet("""
            QMessageBox {
                background: #f4f6fb;
                color: #111827;
            }
            QMessageBox QLabel {
                color: #111827;
                font-size: 13px;
            }
            QMessageBox QPushButton {
                background: #ffffff;
                color: #111827;
                border: 1px solid #e5e7eb;
                border-radius: 7px;
                padding: 8px 18px;
                min-width: 72px;
                font-weight: 700;
            }
            QMessageBox QPushButton:hover {
                border-color: #1a73e8;
                background: #eef4ff;
            }
        """)
        reply = reply_box.exec()
        if reply == QMessageBox.Yes:
            try:
                self.db.delete_employee(employee["id"])
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete: {e}")

    def _delete_selected(self):
        employee = self._employee_by_row(self._table.currentRow())
        if employee:
            self._delete_employee(employee)
