"""Cameras page for managing RTSP camera streams."""

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QLineEdit, QComboBox, QMessageBox,
    QDialog, QFormLayout, QCheckBox, QDialogButtonBox,
)
from PySide6.QtCore import Qt
from typing import Optional

from ..widgets import SectionHeader, Pill
from ..database import Database


class CameraDialog(QDialog):
    """Dialog for adding / editing a camera."""

    def __init__(self, camera: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.camera = camera
        self.setWindowTitle("Edit Camera" if camera else "Add Camera")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._build_ui()
        if camera:
            self._populate(camera)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)

        self.setStyleSheet("QDialog { background:#f4f6fb; color:#111827; } QLabel { color:#111827; } QLineEdit, QComboBox { background:#ffffff; color:#111827; border:1px solid #e5e7eb; border-radius:7px; padding:10px 13px; } QDialogButtonBox QPushButton { background:#ffffff; color:#111827; border:1px solid #e5e7eb; border-radius:7px; padding:9px 16px; font-weight:700; } QDialogButtonBox QPushButton:hover { border-color:#1a73e8; background:#eef4ff; }")
        title = QLabel("Edit Camera" if self.camera else "New Camera")
        title.setProperty("class", "page-title")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignRight)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Main Entrance")
        form.addRow("Name", self._name_input)

        self._url_input = QLineEdit()
        self._url_input.setPlaceholderText("rtsp://192.168.1.100:554/stream")
        form.addRow("RTSP URL", self._url_input)

        self._role_combo = QComboBox()
        self._role_combo.addItems(["general", "check_in", "check_out"])
        form.addRow("Role", self._role_combo)

        self._username_input = QLineEdit()
        self._username_input.setPlaceholderText("Optional")
        form.addRow("Username", self._username_input)

        self._password_input = QLineEdit()
        self._password_input.setPlaceholderText("Optional")
        self._password_input.setEchoMode(QLineEdit.Password)
        form.addRow("Password", self._password_input)

        self._enabled_check = QCheckBox("Enabled")
        self._enabled_check.setChecked(True)
        form.addRow("Status", self._enabled_check)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate(self, camera: dict):
        self._name_input.setText(camera.get("name", ""))
        self._url_input.setText(camera.get("rtsp_url", ""))
        idx = self._role_combo.findText(camera.get("camera_role", "general"))
        if idx >= 0:
            self._role_combo.setCurrentIndex(idx)
        self._username_input.setText(camera.get("rtsp_username") or "")
        self._password_input.setText(camera.get("rtsp_password") or "")
        self._enabled_check.setChecked(bool(camera.get("enabled")))

    def get_data(self) -> dict:
        return {
            "id": self.camera.get("id") if self.camera else None,
            "name": self._name_input.text().strip(),
            "rtsp_url": self._url_input.text().strip(),
            "camera_role": self._role_combo.currentText(),
            "rtsp_username": self._username_input.text().strip() or None,
            "rtsp_password": self._password_input.text().strip() or None,
            "enabled": self._enabled_check.isChecked(),
        }


class CamerasPage(QWidget):
    """Cameras management page with table and CRUD."""

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
        title = QLabel("Cameras")
        title.setProperty("class", "page-title")
        desc = QLabel("Manage RTSP camera streams and their roles")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search cameras...")
        self.search_input.setMinimumWidth(200)
        self.search_input.textChanged.connect(self._filter_table)
        actions.addWidget(self.search_input)

        self.add_btn = QPushButton("+ Add Camera")
        self.add_btn.setProperty("class", "primary")
        self.add_btn.setStyleSheet("QPushButton { background:#1a73e8; color:#ffffff; border:1px solid #1a73e8; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { background:#1765cc; border-color:#1765cc; }")
        self.add_btn.clicked.connect(self._add_camera)
        actions.addWidget(self.add_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self.refresh_btn)

        hdr_layout.addLayout(actions)
        layout.addWidget(header)

        # Table
        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "Name", "RTSP URL", "Role", "Username",
            "Status", "Created", "Updated", "ID"
        ])
        self._table.horizontalHeader().setStretchLastSection(False)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.Stretch)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        for i in range(2, 7):
            header_view.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("""
            QTableWidget { alternate-background-color: rgba(155, 173, 200, 0.03); }
        """)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(52)
        self._table.setColumnHidden(7, True)  # Hide ID
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._context_menu)
        self._table.doubleClicked.connect(self._edit_selected)
        layout.addWidget(self._table)

        # Footer
        footer = QWidget()
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        self._count_label = QLabel("0 cameras")
        self._count_label.setStyleSheet("color: #6b7d9a; font-size: 12px;")
        footer_layout.addWidget(self._count_label)
        footer_layout.addStretch()
        layout.addWidget(footer)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        self._cameras = self.db.list_cameras()
        self._populate_table(self._cameras)

    def _populate_table(self, cameras):
        self._table.setRowCount(len(cameras))
        for row_idx, cam in enumerate(cameras):
            self._table.setItem(row_idx, 0, QTableWidgetItem(cam.get("name", "")))
            self._table.setItem(row_idx, 1, QTableWidgetItem(cam.get("rtsp_url", "")))
            self._table.setItem(row_idx, 2, QTableWidgetItem(cam.get("camera_role", "general")))

            uname = cam.get("rtsp_username") or "-"
            self._table.setItem(row_idx, 3, QTableWidgetItem(uname))

            enabled = bool(cam.get("enabled"))
            status_item = QTableWidgetItem("Enabled" if enabled else "Disabled")
            status_item.setForeground(Qt.green if enabled else Qt.gray)
            self._table.setItem(row_idx, 4, status_item)

            created = cam.get("created_at", "")
            if created:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    created = dt.strftime("%b %d, %Y")
                except Exception:
                    pass
            self._table.setItem(row_idx, 5, QTableWidgetItem(created))

            updated = cam.get("updated_at", "")
            if updated:
                try:
                    from datetime import datetime
                    dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    updated = dt.strftime("%b %d, %Y")
                except Exception:
                    pass
            self._table.setItem(row_idx, 6, QTableWidgetItem(updated))
            self._table.setItem(row_idx, 7, QTableWidgetItem(cam.get("id", "")))

        self._count_label.setText(f"{len(cameras)} cameras")

    def _filter_table(self, text):
        if not hasattr(self, '_cameras'):
            return
        if not text.strip():
            self._populate_table(self._cameras)
            return
        filtered = [
            c for c in self._cameras
            if text.lower() in c.get("name", "").lower()
            or text.lower() in c.get("rtsp_url", "").lower()
        ]
        self._populate_table(filtered)

    def _add_camera(self):
        dialog = CameraDialog(parent=self)
        if dialog.exec():
            try:
                self.db.save_camera(dialog.get_data())
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

    def _edit_selected(self):
        row = self._table.currentRow()
        if row < 0:
            return
        cam_id = self._table.item(row, 7).text()
        camera = next((c for c in self._cameras if c["id"] == cam_id), None)
        if not camera:
            return
        dialog = CameraDialog(camera, self)
        if dialog.exec():
            try:
                self.db.save_camera(dialog.get_data())
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))

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
        edit_action = menu.addAction("Edit Camera")
        delete_action = menu.addAction("Delete Camera")
        action = menu.exec(self._table.mapToGlobal(pos))
        if action == edit_action:
            self._edit_selected()
        elif action == delete_action:
            self._delete_selected()

    def _delete_selected(self):
        row = self._table.currentRow()
        if row < 0:
            return
        cam_id = self._table.item(row, 7).text()
        name = self._table.item(row, 0).text()
        reply = QMessageBox.question(
            self, "Delete Camera",
            f"Delete camera '{name}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.db.delete_camera(cam_id)
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))
