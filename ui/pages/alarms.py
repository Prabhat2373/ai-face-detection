"""Alarms page showing unknown face security alerts and detection snapshots."""

import os
import json
from datetime import datetime, timezone

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QComboBox, QMessageBox, QDialog,
)
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QBrush, QPixmap

from ..widgets import StatCard
from ..database import Database


class AlarmsPage(QWidget):
    """Unknown person security alarms and detection snapshots page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database.get()
        self._build_ui()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(3000)

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
        title = QLabel("Unknown Person Alarms")
        title.setProperty("class", "page-title")
        desc = QLabel("Real-time security alerts triggered when an unrecognized face is detected")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()

        # Filter & Action controls
        controls = QHBoxLayout()
        controls.setSpacing(8)

        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All Unknown Alarms", "Today Only"])
        self._filter_combo.setMinimumWidth(160)
        self._filter_combo.currentTextChanged.connect(self._apply_filter)
        controls.addWidget(QLabel("Filter:"))
        controls.addWidget(self._filter_combo)

        self.clear_btn = QPushButton("Clear Alarms")
        self.clear_btn.setStyleSheet("QPushButton { background: #ef4444; color: #ffffff; font-weight: bold; border-radius: 6px; padding: 8px 16px; } QPushButton:hover { background: #dc2626; }")
        self.clear_btn.clicked.connect(self._clear_events)
        controls.addWidget(self.clear_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet("QPushButton { background: #ffffff; color: #111827; border: 1px solid #e5e7eb; font-weight: bold; border-radius: 6px; padding: 8px 16px; } QPushButton:hover { background: #eef4ff; border-color: #1a73e8; }")
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)

        hdr_layout.addLayout(controls)
        layout.addWidget(header)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self._total_alarms_card = self._mini_stat("Total Unknown Alarms", "0", "#ef4444")
        self._today_alarms_card = self._mini_stat("Active Today", "0", "#f97316")

        stats_row.addWidget(self._total_alarms_card)
        stats_row.addWidget(self._today_alarms_card)
        stats_row.addStretch()
        layout.addLayout(stats_row)

        # Unknown Alarms Table
        self._table = QTableWidget()
        self._table.setColumnCount(7)
        self._table.setHorizontalHeaderLabels([
            "#", "Snapshot", "Camera", "Timestamp", "Confidence", "Status", "Action"
        ])
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)  # #
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)  # Snapshot
        header_view.setSectionResizeMode(2, QHeaderView.Stretch)           # Camera
        header_view.setSectionResizeMode(3, QHeaderView.ResizeToContents)  # Timestamp
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)  # Confidence
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)  # Status
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents)  # Action

        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setMinimumHeight(380)
        layout.addWidget(self._table)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _mini_stat(self, label: str, value: str, color: str) -> QFrame:
        card = QFrame()
        card.setProperty("class", "stat-card")
        card.setMinimumHeight(80)
        card.setMinimumWidth(220)
        clayout = QVBoxLayout(card)
        clayout.setContentsMargins(16, 12, 16, 12)
        clayout.setSpacing(4)

        lbl = QLabel(label.upper())
        lbl.setProperty("class", "stat-label")
        clayout.addWidget(lbl)

        val = QLabel(value)
        val.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: 700; background: transparent;")
        clayout.addWidget(val)
        return card

    def _fetch_unknown_alarms(self):
        """Fetch unknown person alarm events from the database."""
        events = []
        sync_rows = self.db.list_alarm_events(100)
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        for row in sync_rows:
            event_type = row.get("event_type", "")
            if event_type != "alarm.triggered":
                continue

            payload_text = row.get("payload", "{}")
            try:
                payload = json.loads(payload_text)
            except Exception:
                payload = {}

            snapshot = payload.get("snapshot") or {}
            faces = payload.get("faces") or []
            best_face = max(faces, key=lambda f: float(f.get("confidence") or 0.0), default={})
            confidence = float(best_face.get("confidence") or snapshot.get("confidence") or 0.0)
            camera = payload.get("cameraName") or payload.get("cameraId") or payload.get("cameraRole") or "Front Gate"
            snapshot_path = snapshot.get("path")
            ts = row.get("created_at") or payload.get("timestamp") or ""

            # Check if today
            is_today = False
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    is_today = dt.astimezone().strftime("%Y-%m-%d") == today_str
                except Exception:
                    is_today = ts[:10] == today_str

            events.append({
                "id": row.get("id"),
                "camera": camera,
                "timestamp": ts,
                "is_today": is_today,
                "confidence": confidence,
                "snapshot_path": snapshot_path,
                "status": "Triggered",
            })

        events.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
        return events

    def refresh(self):
        self._events = self._fetch_unknown_alarms()
        self._apply_filter()

        # Update stats
        total_alarms = len(self._events)
        today_alarms = sum(1 for e in self._events if e.get("is_today"))

        self._total_alarms_card.layout().itemAt(1).widget().setText(str(total_alarms))
        self._today_alarms_card.layout().itemAt(1).widget().setText(str(today_alarms))

    def _apply_filter(self):
        if not hasattr(self, "_events"):
            return
        filter_text = self._filter_combo.currentText()
        if filter_text == "Today Only":
            filtered = [e for e in self._events if e.get("is_today")]
        else:
            filtered = self._events

        self._populate_table(filtered)

    def _populate_table(self, events):
        self._table.setRowCount(len(events))
        self._table.verticalHeader().setDefaultSectionSize(54)

        for idx, evt in enumerate(events, start=1):
            row_idx = idx - 1

            # Index
            item_idx = QTableWidgetItem(str(idx))
            item_idx.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row_idx, 0, item_idx)

            # Snapshot thumbnail
            snap_path = evt.get("snapshot_path")
            if snap_path and os.path.exists(snap_path):
                lbl_snap = QLabel()
                pix = QPixmap(snap_path)
                if not pix.isNull():
                    pix = pix.scaled(44, 44, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                    lbl_snap.setPixmap(pix)
                    lbl_snap.setCursor(Qt.PointingHandCursor)
                    lbl_snap.setToolTip("Click to view unknown snapshot")
                    lbl_snap.mousePressEvent = lambda event, path=snap_path: self._show_snapshot_dialog(path)
                    self._table.setCellWidget(row_idx, 1, lbl_snap)
                else:
                    self._table.setItem(row_idx, 1, QTableWidgetItem("-"))
            else:
                self._table.setItem(row_idx, 1, QTableWidgetItem("-"))

            # Camera
            self._table.setItem(row_idx, 2, QTableWidgetItem(str(evt.get("camera") or "-")))

            # Timestamp
            ts = evt.get("timestamp", "")
            formatted_ts = "-"
            if ts:
                try:
                    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                    formatted_ts = dt.astimezone().strftime("%d %b %Y %I:%M:%S %p")
                except Exception:
                    formatted_ts = str(ts)
            self._table.setItem(row_idx, 3, QTableWidgetItem(formatted_ts))

            # Confidence
            conf = evt.get("confidence", 0.0)
            val = conf * 100.0 if conf <= 1.0 else conf
            conf_text = f"{val:.1f}%" if val > 0 else "-"
            item_conf = QTableWidgetItem(conf_text)
            item_conf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row_idx, 4, item_conf)

            # Status (Red Triggered Badge)
            item_status = QTableWidgetItem("Triggered")
            item_status.setBackground(QBrush(QColor(254, 226, 226)))
            item_status.setForeground(QBrush(QColor(220, 38, 38)))
            self._table.setItem(row_idx, 5, item_status)

            # Action button
            if snap_path and os.path.exists(snap_path):
                btn_view = QPushButton("View")
                btn_view.setStyleSheet("QPushButton { background: #1a73e8; color: #ffffff; font-weight: bold; border-radius: 4px; padding: 4px 12px; } QPushButton:hover { background: #1765cc; }")
                btn_view.clicked.connect(lambda _, path=snap_path: self._show_snapshot_dialog(path))
                self._table.setCellWidget(row_idx, 6, btn_view)
            else:
                self._table.setItem(row_idx, 6, QTableWidgetItem("-"))

    def _show_snapshot_dialog(self, path: str):
        """Display unknown person snapshot modal dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Unknown Person Detection Snapshot")
        dialog.setMinimumSize(640, 480)
        d_layout = QVBoxLayout(dialog)

        title = QLabel("⚠️ Unknown Person Alarm Snapshot")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #dc2626; margin-bottom: 8px;")
        d_layout.addWidget(title, alignment=Qt.AlignCenter)

        img_lbl = QLabel()
        pix = QPixmap(path)
        if not pix.isNull():
            img_lbl.setPixmap(pix.scaled(720, 540, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        img_lbl.setAlignment(Qt.AlignCenter)
        d_layout.addWidget(img_lbl)

        btn_close = QPushButton("Close")
        btn_close.setStyleSheet("QPushButton { background: #1a73e8; color: #ffffff; font-weight: bold; padding: 8px 20px; border-radius: 6px; }")
        btn_close.clicked.connect(dialog.accept)
        d_layout.addWidget(btn_close, alignment=Qt.AlignCenter)
        dialog.exec()

    def _clear_events(self):
        reply = QMessageBox.question(
            self, "Clear Alarms",
            "Are you sure you want to clear all unknown person alarms?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.db.clear_sync_events()
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))
