"""Departments page for managing company departments."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QLineEdit, QMessageBox,
    QDialog, QFormLayout, QTextEdit, QDialogButtonBox,
)
from PySide6.QtCore import Qt, QSize
from typing import Optional

from ..widgets import SectionHeader, get_edit_icon, get_delete_icon
from ..database import Database


class DepartmentDialog(QDialog):
    """Dialog for adding / editing a department."""

    def __init__(self, department: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.department = department
        self.setWindowTitle("Edit Department" if department else "Add Department")
        self.setMinimumWidth(400)
        self.setModal(True)
        self._build_ui()
        if department:
            self._populate(department)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        self.setStyleSheet("""
            QDialog { background: #f4f6fb; color: #111827; }
            QLabel { color: #111827; }
            QLineEdit, QTextEdit { background: #ffffff; color: #111827; border: 1px solid #e5e7eb; border-radius: 7px; padding: 10px 13px; }
            QLineEdit:focus, QTextEdit:focus { border-color: #1a73e8; }
            QDialogButtonBox QPushButton { background: #ffffff; color: #111827; border: 1px solid #e5e7eb; border-radius: 7px; padding: 9px 16px; font-weight: 700; }
            QDialogButtonBox QPushButton:hover { border-color: #1a73e8; background: #eef4ff; }
        """)

        title = QLabel("Edit Department" if self.department else "New Department")
        title.setProperty("class", "page-title")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignRight)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Engineering")
        form.addRow("Name", self._name_input)

        self._desc_input = QTextEdit()
        self._desc_input.setPlaceholderText("Optional description")
        self._desc_input.setMaximumHeight(80)
        form.addRow("Description", self._desc_input)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, department: dict):
        self._name_input.setText(department.get("name", ""))
        self._desc_input.setPlainText(department.get("description", ""))

    def get_data(self) -> dict:
        return {
            "id": self.department.get("id") if self.department else None,
            "name": self._name_input.text().strip(),
            "description": self._desc_input.toPlainText().strip(),
        }


class DepartmentsPage(QWidget):
    """Departments page with table and CRUD actions."""

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
        title = QLabel("Departments")
        title.setProperty("class", "page-title")
        desc = QLabel("Organize employees into departments")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search departments...")
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._filter_table)
        actions.addWidget(self.search_input)

        self.add_btn = QPushButton("+ Add Department")
        self.add_btn.setProperty("class", "primary")
        self.add_btn.setStyleSheet("background: #1a73e8; color: #ffffff; border: 1px solid #1a73e8; border-radius: 7px; padding: 9px 16px; font-weight: 700;")
        self.add_btn.clicked.connect(self._add_department)
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
            "Name", "Description", "Employees", "Created", "Action", "ID"
        ])
        self._table.horizontalHeader().setStretchLastSection(False)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget { alternate-background-color: rgba(155, 173, 200, 0.03); }
        """)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setColumnHidden(5, True)  # Hide ID
        layout.addWidget(self._table)

        # Footer
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self._count_label = QLabel("0 departments")
        self._count_label.setStyleSheet("color: #6b7d9a; font-size: 12px;")
        footer_layout.addWidget(self._count_label)
        footer_layout.addStretch()
        layout.addWidget(footer)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        self._departments = self.db.list_departments()
        self._populate_table(self._departments)

    def _populate_table(self, departments):
        self._table.setRowCount(len(departments))
        for row_idx, dept in enumerate(departments):
            self._table.setItem(row_idx, 0, QTableWidgetItem(dept.get("name", "")))
            self._table.setItem(row_idx, 1, QTableWidgetItem(dept.get("description", "")))
            self._table.setItem(row_idx, 2, QTableWidgetItem(str(dept.get("employee_count", 0))))

            created = dept.get("created_at", "")
            if created:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    created = dt.strftime("%b %d, %Y")
                except Exception:
                    pass
            self._table.setItem(row_idx, 3, QTableWidgetItem(created))
            self._table.setCellWidget(row_idx, 4, self._build_action_widget(dept))
            self._table.setItem(row_idx, 5, QTableWidgetItem(dept.get("id", "")))

        self._count_label.setText(f"{len(departments)} departments")

    def _filter_table(self, text):
        if not hasattr(self, '_departments'):
            return
        if not text.strip():
            self._populate_table(self._departments)
            return
        filtered = [
            d for d in self._departments
            if text.lower() in d.get("name", "").lower()
        ]
        self._populate_table(filtered)

    def _add_department(self):
        dialog = DepartmentDialog(parent=self)
        if dialog.exec():
            try:
                self.db.save_department(dialog.get_data())
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _department_by_row(self, row: int) -> Optional[dict]:
        if row < 0 or row >= self._table.rowCount():
            return None
        item = self._table.item(row, 5)
        dept_id = item.text() if item else ""
        return next((d for d in getattr(self, "_departments", []) if d["id"] == dept_id), None)

    def _build_action_widget(self, department: dict) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(8)
        layout.setAlignment(Qt.AlignCenter)

        edit_btn = QPushButton()
        edit_btn.setIcon(get_edit_icon("#ffffff", 16))
        edit_btn.setIconSize(QSize(16, 16))
        edit_btn.setToolTip("Edit Department")
        edit_btn.setCursor(Qt.PointingHandCursor)
        edit_btn.setStyleSheet("QPushButton { background:#1a73e8; color:#ffffff; border:none; border-radius:6px; padding:6px 10px; min-width:32px; min-height:28px; } QPushButton:hover { background:#1557b0; }")
        edit_btn.clicked.connect(lambda _checked=False, dept=department: self._edit_department(dept))
        layout.addWidget(edit_btn)

        delete_btn = QPushButton()
        delete_btn.setIcon(get_delete_icon("#ffffff", 16))
        delete_btn.setIconSize(QSize(16, 16))
        delete_btn.setToolTip("Delete Department")
        delete_btn.setCursor(Qt.PointingHandCursor)
        delete_btn.setStyleSheet("QPushButton { background:#ef4444; color:#ffffff; border:none; border-radius:6px; padding:6px 10px; min-width:32px; min-height:28px; } QPushButton:hover { background:#dc2626; }")
        delete_btn.clicked.connect(lambda _checked=False, dept=department: self._delete_department(dept))
        layout.addWidget(delete_btn)
        return widget

    def _edit_department(self, department: dict):
        dialog = DepartmentDialog(department, self)
        if dialog.exec():
            try:
                self.db.save_department(dialog.get_data())
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _edit_selected(self):
        department = self._department_by_row(self._table.currentRow())
        if department:
            self._edit_department(department)

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
        edit_action = menu.addAction("Edit Department")
        delete_action = menu.addAction("Delete Department")
        action = menu.exec(self._table.mapToGlobal(pos))
        if action == edit_action:
            self._edit_selected()
        elif action == delete_action:
            self._delete_selected()

    def _delete_department(self, department: dict):
        box = QMessageBox(self)
        box.setWindowTitle("Delete Department")
        box.setText(f"Delete department '{department.get('name', '')}'?\nEmployees in this department will be unassigned.")
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        box.setDefaultButton(QMessageBox.No)
        box.setStyleSheet("QMessageBox { background:#f4f6fb; color:#111827; } QMessageBox QLabel { color:#111827; } QMessageBox QPushButton { background:#fff; color:#111827; border:1px solid #e5e7eb; border-radius:7px; padding:8px 18px; min-width:72px; font-weight:700; } QMessageBox QPushButton:hover { background:#eef4ff; border-color:#1a73e8; }")
        if box.exec() == QMessageBox.Yes:
            try:
                self.db.delete_department(department["id"])
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _delete_selected(self):
        department = self._department_by_row(self._table.currentRow())
        if department:
            self._delete_department(department)
