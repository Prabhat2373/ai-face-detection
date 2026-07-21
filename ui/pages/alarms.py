"""Alarms page showing system notifications, detection events, and error logs."""

import json

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QComboBox, QMessageBox,
)
from PySide6.QtCore import QSize, Qt, QTimer
from datetime import datetime, timezone

from ..widgets import SectionHeader, Pill
from ..database import Database
from PySide6.QtGui import QColor, QPixmap


class AlarmsPage(QWidget):
    """System alarms, notifications, and detection events page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database.get()
        self._build_ui()
        self.refresh()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(10000)

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
        title = QLabel("Alarms & Events")
        title.setProperty("class", "page-title")
        desc = QLabel("System notifications, detection events, and error logs")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()

        # Filter controls
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._filter_combo = QComboBox()
        self._filter_combo.addItems(["All Events", "Detection", "Error", "System", "Sync"])
        self._filter_combo.currentTextChanged.connect(self._apply_filter)
        controls.addWidget(QLabel("Filter:"))
        controls.addWidget(self._filter_combo)

        self.clear_btn = QPushButton("Clear Events")
        self.clear_btn.setProperty("class", "danger")
        self.clear_btn.clicked.connect(self._clear_events)
        controls.addWidget(self.clear_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)

        hdr_layout.addLayout(controls)
        layout.addWidget(header)

        # Stats row
        stats_row = QHBoxLayout()
        stats_row.setSpacing(12)

        self._detection_card = self._mini_stat("Recent Detections", "0", "#86efac")
        self._error_card = self._mini_stat("Errors", "0", "#fb7185")
        self._sync_card = self._mini_stat("Sync Events", "0", "#bfdbfe")

        for card in [self._detection_card, self._error_card, self._sync_card]:
            stats_row.addWidget(card)
        layout.addLayout(stats_row)

        # Events table
        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "Snapshot", "Type", "Timestamp", "Details", "Status", "Retries"
        ])
        self._table.horizontalHeader().setStretchLastSection(True)
        header_view = self._table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(3, QHeaderView.Stretch)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def _mini_stat(self, label: str, value: str, color: str) -> QFrame:
        card = QFrame()
        card.setProperty("class", "stat-card")
        card.setMinimumHeight(80)
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

    def _generate_events(self):
        """Generate simulated events from database state for the UI demonstration."""
        events = []

        # Detection events from attendance records
        for rec in self.db.list_attendance()[:10]:
            events.append({
                "type": "Detection",
                "timestamp": rec.get("last_appearance", ""),
                "details": f"Face matched: {rec.get('label', 'Unknown')} (confidence: {rec.get('max_confidence', 0):.2f})",
                "status": "Success",
                "retries": 0,
            })

        # Sync events from store (no raw SQL in UI)
        for row in self.db.list_all_sync_events(20):
            payload_text = row.get("payload", "{}")
            try:
                payload = json.loads(payload_text)
            except Exception:
                payload = {}
            event_type = row.get("event_type", "unknown")
            snapshot = payload.get("snapshot") or {}
            faces = payload.get("faces") or []
            best_face = max(faces, key=lambda face: float(face.get("confidence") or 0), default={})
            confidence = float(best_face.get("confidence") or snapshot.get("confidence") or 0)
            camera = payload.get("cameraName") or payload.get("cameraId") or payload.get("cameraRole") or "-"
            details = f"[{event_type}] {payload_text}"
            if event_type == "alarm.triggered":
                details = f"Unknown person detected · Camera {camera}"
            events.append({
                "type": "Alarm" if event_type == "alarm.triggered" else "Sync",
                "timestamp": row.get("created_at", ""),
                "details": details[:180],
                "status": "Active" if event_type == "alarm.triggered" else ("Synced" if row.get("synced_at") else "Pending"),
                "retries": row.get("retry_count", 0),
                "snapshot_path": snapshot.get("path"),
                "confidence": confidence,
            })

        # Error simulation from cameras with issues
        for cam in self.db.list_cameras():
            if not cam.get("enabled") and cam.get("name"):
                events.append({
                    "type": "System",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"Camera '{cam.get('name')}' is disabled",
                    "status": "Warning",
                    "retries": 0,
                })

        events.sort(key=lambda e: e["timestamp"], reverse=True)
        return events

    def refresh(self):
        self._events = self._generate_events()
        self._apply_filter()

        # Update stats
        detections = sum(1 for e in self._events if e["type"] == "Detection")
        errors = sum(1 for e in self._events if e["status"] == "Error" or e["status"] == "Warning")
        syncs = sum(1 for e in self._events if e["type"] == "Sync")

        self._detection_card.layout().itemAt(1).widget().setText(str(detections))
        self._error_card.layout().itemAt(1).widget().setText(str(errors))
        self._sync_card.layout().itemAt(1).widget().setText(str(syncs))

    def _apply_filter(self):
        if not hasattr(self, '_events'):
            return
        filter_text = self._filter_combo.currentText()
        if filter_text == "All Events":
            filtered = self._events
        else:
            event_type = filter_text.replace(" Events", "")
            filtered = [e for e in self._events if e["type"] == event_type]

        self._populate_table(filtered)

    def _populate_table(self, events):
        self._table.setRowCount(len(events))
        self._table.setIconSize(QSize(72, 46))
        self._table.verticalHeader().setDefaultSectionSize(58)
        for row_idx, evt in enumerate(events):
            snapshot_label = QLabel()
            snapshot_label.setAlignment(Qt.AlignCenter)
            snapshot_path = evt.get("snapshot_path")
            if snapshot_path:
                pixmap = QPixmap(str(snapshot_path))
                if not pixmap.isNull():
                    snapshot_label.setPixmap(pixmap.scaled(72, 46, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    snapshot_label.setText("No image")
            else:
                snapshot_label.setText("-")
            self._table.setCellWidget(row_idx, 0, snapshot_label)

            self._table.setItem(row_idx, 1, QTableWidgetItem(evt["type"]))

            ts = evt.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    ts = dt.strftime("%b %d, %Y  %H:%M:%S")
                except Exception:
                    pass
            self._table.setItem(row_idx, 2, QTableWidgetItem(ts))
            self._table.setItem(row_idx, 3, QTableWidgetItem(evt.get("details", "")))

            status = evt.get("status", "")
            status_item = QTableWidgetItem(status)
            if status in ("Success", "Synced"):
                status_item.setForeground(Qt.green)
            elif status in ("Error", "Active"):
                status_item.setForeground(Qt.red)
            elif status == "Warning":
                status_item.setForeground(QColor("#fbbf24"))
            else:
                status_item.setForeground(QColor("#9badc8"))
            self._table.setItem(row_idx, 4, status_item)
            retry_text = str(evt.get("retries", 0))
            if evt.get("confidence"):
                retry_text = f"{float(evt['confidence']) * 100:.1f}%"
            self._table.setItem(row_idx, 5, QTableWidgetItem(retry_text))

    def _clear_events(self):
        reply = QMessageBox.question(
            self, "Clear Events",
            "Clear all sync events from the database?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                self.db.clear_sync_events()
                self.refresh()
            except Exception as e:
                QMessageBox.warning(self, "Error", str(e))
