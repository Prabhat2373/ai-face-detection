"""Employees page for managing employee records and face registration."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QLineEdit, QComboBox, QMessageBox,
    QDialog, QFormLayout, QDialogButtonBox, QCheckBox,
)
from PySide6.QtCore import Qt, QTimer
from typing import Optional

from ..widgets import SectionHeader, EmptyState
from ..database import Database


class EmployeeDialog(QDialog):
    """Dialog for adding / editing an employee."""

    def __init__(self, employee: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.employee = employee
        self.db = Database.get()
        self.setWindowTitle("Edit Employee" if employee else "Add Employee")
        self.setMinimumWidth(420)
        self.setModal(True)
        self._build_ui()
        if employee:
            self._populate(employee)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Edit Employee" if self.employee else "New Employee")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #edf3ff;")
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

        layout.addLayout(form)

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

    def get_data(self) -> dict:
        return {
            "id": self.employee.get("id") if self.employee else None,
            "name": self._name_input.text().strip(),
            "employee_code": self._code_input.text().strip(),
            "role": self._role_input.text().strip(),
            "department_id": self._dept_combo.currentData() or None,
            "active": self._active_check.isChecked(),
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
        self.add_btn.clicked.connect(self._add_employee)
        actions.addWidget(self.add_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_btn)

        hdr_layout.addLayout(actions)
        layout.addWidget(header)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Name", "Code", "Role", "Department", "Status", "ID"
        ])
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget { alternate-background-color: rgba(155, 173, 200, 0.03); }
        """)
        self._table.verticalHeader().setVisible(False)
        self._table.setColumnHidden(5, True)  # Hide ID column
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self._table)

        # Count
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self._count_label = QLabel("0 employees")
        self._count_label.setStyleSheet("color: #6b7d9a; font-size: 12px;")
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
            self._table.setItem(row_idx, 0, QTableWidgetItem(emp.get("name", "")))
            self._table.setItem(row_idx, 1, QTableWidgetItem(emp.get("employee_code", "")))
            self._table.setItem(row_idx, 2, QTableWidgetItem(emp.get("role", "")))
            self._table.setItem(row_idx, 3, QTableWidgetItem(emp.get("department_name", "-")))
            status = "Active" if emp.get("active") else "Inactive"
            item = QTableWidgetItem(status)
            item.setForeground(Qt.green if emp.get("active") else Qt.gray)
            self._table.setItem(row_idx, 4, item)
            self._table.setItem(row_idx, 5, QTableWidgetItem(emp.get("id", "")))

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

    def _add_employee(self):
        dialog = EmployeeDialog(parent=self)
        if dialog.exec():
            data = dialog.get_data()
            try:
                self.db.save_employee(data)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not save employee: {e}")

    def _edit_selected(self):
        row = self._table.currentRow()
        if row < 0:
            return
        emp_id = self._table.item(row, 5).text()
        employee = next((e for e in self._employees if e["id"] == emp_id), None)
        if not employee:
            return
        dialog = EmployeeDialog(employee, self)
        if dialog.exec():
            data = dialog.get_data()
            try:
                self.db.save_employee(data)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not update employee: {e}")

    def _context_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background: #16233d;
                border: 1px solid rgba(155, 173, 200, 0.18);
                border-radius: 8px;
                padding: 4px;
            }
            QMenu::item {
                padding: 8px 24px;
                border-radius: 4px;
                color: #edf3ff;
            }
            QMenu::item:hover {
                background: rgba(102, 224, 199, 0.12);
                color: #66e0c7;
            }
        """)

        edit_action = menu.addAction("Edit Employee")
        delete_action = menu.addAction("Delete Employee")

        action = menu.exec(self._table.mapToGlobal(pos))
        if action == edit_action:
            self._edit_selected()
        elif action == delete_action:
            self._delete_selected()

    def _delete_selected(self):
        row = self._table.currentRow()
        if row < 0:
            return
        emp_id = self._table.item(row, 5).text()
        name = self._table.item(row, 0).text()
        reply = QMessageBox.question(
            self, "Delete Employee",
            f"Are you sure you want to delete {name}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.db.delete_employee(emp_id)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not delete: {e}")
