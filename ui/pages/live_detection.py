"""Live Detection page with camera feed viewer for the FaceAgent app."""

import os
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QGridLayout, QScrollArea,
)
from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QSoundEffect

from ..widgets import StatCard, SectionHeader, Pill, EmptyState
from ..backend_client import BackendClient
from ..database import Database


class CameraFeedWidget(QFrame):
    """A widget showing a single camera feed with overlay info."""

    def __init__(self, camera: dict, frame_bytes: bytes | None = None, parent=None):
        super().__init__(parent)
        self.camera = camera
        self._last_pixmap = QPixmap()
        self._last_faces: list[dict] = []
        self.setStyleSheet("""
            CameraFeedWidget {
                background: #050b14;
                border: 1px solid rgba(155, 173, 200, 0.18);
                border-radius: 10px;
            }
        """)
        self.setMinimumSize(320, 240)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # Camera name / role header
        header = QHBoxLayout()
        header.setSpacing(8)
        name_label = QLabel(camera.get("name", "Camera"))
        name_label.setStyleSheet("color: #f8fafc; font-size: 14px; font-weight: 700; background: transparent;")
        header.addWidget(name_label)

        role = camera.get("camera_role", "general")
        role_pill = Pill(role.capitalize(), "sync" if role != "general" else "idle")
        header.addWidget(role_pill)
        header.addStretch()

        status = "Enabled" if camera.get("enabled") else "Disabled"
        status_pill = Pill(status, "running" if camera.get("enabled") else "idle")
        header.addWidget(status_pill)
        layout.addLayout(header)

        # Placeholder for stream area
        self.feed_label = QLabel("No Feed")
        self.feed_label.setAlignment(Qt.AlignCenter)
        self.feed_label.setMinimumHeight(180)
        self.feed_label.setStyleSheet("""
            color: #6b7d9a;
            font-size: 14px;
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
        """)
        layout.addWidget(self.feed_label, 1)

        # RTSP URL
        url_label = QLabel(camera.get("rtsp_url", "No URL"))
        url_label.setStyleSheet("color: #94a3b8; font-size: 11px; background: transparent;")
        url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(url_label)

        self.set_frame(frame_bytes)

    def set_frame(self, frame_bytes: bytes | None, faces: list[dict] | None = None):
        if faces is not None:
            self._last_faces = faces
        if not frame_bytes:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(frame_bytes):
            return
        self._last_pixmap = pixmap
        self._paint_frame()
        self.feed_label.setText("")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._paint_frame()

    def _paint_frame(self):
        if self._last_pixmap.isNull():
            return

        target_size = self.feed_label.size()
        scaled = self._last_pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QPixmap(target_size)
        canvas.fill(QColor("#050b14"))

        painter = QPainter(canvas)
        offset_x = (target_size.width() - scaled.width()) / 2
        offset_y = (target_size.height() - scaled.height()) / 2
        painter.drawPixmap(int(offset_x), int(offset_y), scaled)

        scale = min(
            scaled.width() / max(1, self._last_pixmap.width()),
            scaled.height() / max(1, self._last_pixmap.height()),
        )
        painter.setFont(QFont("Inter", 11, QFont.Bold))
        for face in self._last_faces:
            box = face.get("box") or {}
            match = face.get("match") or {}
            known = bool(match.get("label"))
            color = QColor("#22c55e" if known else "#f87171")
            painter.setPen(QPen(color, 3))
            x = offset_x + float(box.get("x") or 0) * scale
            y = offset_y + float(box.get("y") or 0) * scale
            w = float(box.get("width") or 0) * scale
            h = float(box.get("height") or 0) * scale
            painter.drawRect(int(x), int(y), int(w), int(h))

            confidence = match.get("confidence", face.get("confidence", 0))
            label = match.get("label") or "Unknown"
            text = f"{label} · {round(float(confidence or 0) * 100)}%"
            metrics = painter.fontMetrics()
            text_width = metrics.horizontalAdvance(text) + 14
            text_y = max(4, int(y) - 24)
            painter.fillRect(int(x), text_y, text_width, 22, QColor("#166534" if known else "#7f1d1d"))
            painter.setPen(QColor("#ffffff"))
            painter.drawText(int(x) + 7, text_y + 16, text)

        painter.end()
        self.feed_label.setPixmap(canvas)


class LiveDetectionPage(QWidget):
    """Live detection page with camera grid and status overview."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.db = Database.get()
        self.backend = BackendClient()
        self._backend_status: dict = {}
        self._feed_widgets: dict[str, CameraFeedWidget] = {}
        self._camera_signature = ""
        self._last_unknown_alarm_at: dict[str, int] = {}
        self._alarm_cooldown_ms = max(500, int(os.getenv("FACEAGENT_UI_ALARM_COOLDOWN_MS", "5000")))
        self._alarm_sound = self._create_alarm_sound()
        self._build_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_backend_status)
        self._refresh_timer.start(1000)
        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._refresh_frames)
        frame_interval_ms = max(50, int(os.getenv("FACEAGENT_UI_FRAME_INTERVAL_MS", "100")))
        self._frame_timer.start(frame_interval_ms)
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
        title = QLabel("Live Detection")
        title.setProperty("class", "page-title")
        desc = QLabel("RTSP feeds, face detection, and recognition")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()

        # Controls
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.camera_selector = QComboBox()
        self.camera_selector.setMinimumWidth(200)
        controls.addWidget(self.camera_selector)

        self.start_btn = QPushButton("Start Detection")
        self.start_btn.setProperty("class", "primary")
        self.start_btn.clicked.connect(self._start_detection)
        controls.addWidget(self.start_btn)

        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop_detection)
        controls.addWidget(self.stop_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("class", "ghost")
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)

        hdr_layout.addLayout(controls)
        layout.addWidget(header)

        # Status row
        self._status_layout = QHBoxLayout()
        self._status_layout.setSpacing(12)
        self._stat_state = StatCard("State", "Idle")
        self._stat_known = StatCard("Known Detections", "0")
        self._stat_unknown = StatCard("Unknown Detections", "0")
        self._stat_registered = StatCard("Registered", "0")
        self._stat_last = StatCard("Last Face", "-")

        for card in [self._stat_state, self._stat_known, self._stat_unknown,
                     self._stat_registered, self._stat_last]:
            self._status_layout.addWidget(card)
        layout.addLayout(self._status_layout)

        # Camera grid
        layout.addWidget(SectionHeader("Camera Feeds", "All available RTSP camera streams"))
        self._camera_grid = QGridLayout()
        self._camera_grid.setSpacing(12)
        layout.addLayout(self._camera_grid)

        # Detected faces panel
        layout.addWidget(SectionHeader("Detected Faces", "Recently recognized faces"))
        self._faces_panel = QFrame()
        self._faces_panel.setProperty("class", "panel")
        faces_layout = QVBoxLayout(self._faces_panel)
        faces_layout.setContentsMargins(14, 14, 14, 14)
        self._faces_label = QLabel("No faces detected yet")
        self._faces_label.setAlignment(Qt.AlignCenter)
        self._faces_label.setProperty("class", "muted")
        self._faces_label.setStyleSheet("font-size: 13px; padding: 20px;")
        faces_layout.addWidget(self._faces_label)
        layout.addWidget(self._faces_panel)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        cameras = self.db.list_cameras()
        self._stat_registered.set_value(str(len(self.db.list_known_faces())))
        self._refresh_backend_status()

        # Update camera selector
        current_text = self.camera_selector.currentText()
        self.camera_selector.clear()
        self.camera_selector.addItem("All Cameras", None)
        for cam in cameras:
            name = cam.get("name", "Unnamed")
            self.camera_selector.addItem(name, cam.get("id"))
        idx = self.camera_selector.findText(current_text)
        if idx >= 0:
            self.camera_selector.setCurrentIndex(idx)

        enabled = [c for c in cameras if c.get("enabled")]
        signature = "|".join(f"{c.get('id')}:{c.get('name')}:{c.get('camera_role')}" for c in enabled)
        if signature == self._camera_signature:
            self._refresh_frames()
            return

        # Update camera grid only when the camera list changes.
        self._camera_signature = signature
        self._feed_widgets = {}
        self._clear_layout(self._camera_grid)
        if not enabled:
            placeholder = QLabel("No enabled cameras available")
            placeholder.setAlignment(Qt.AlignCenter)
            placeholder.setStyleSheet("color: #6b7d9a; font-size: 14px; padding: 40px;")
            self._camera_grid.addWidget(placeholder, 0, 0)
        else:
            cols = max(1, min(3, len(enabled)))
            for idx, cam in enumerate(enabled):
                feed = CameraFeedWidget(cam)
                self._feed_widgets[str(cam.get("id"))] = feed
                row, col = divmod(idx, cols)
                self._camera_grid.addWidget(feed, row, col)
            self._refresh_frames()

    def _refresh_backend_status(self):
        try:
            self._backend_status = self.backend.status()
        except Exception as exc:  # noqa: BLE001
            self._backend_status = {"state": "offline", "lastError": str(exc)}

        state = str(self._backend_status.get("state") or "offline").title()
        self._stat_state.set_value(state)

        camera_statuses = self._backend_status.get("cameras") or []
        all_faces = self._all_current_faces(camera_statuses)
        known_count = sum(1 for face in all_faces if (face.get("match") or {}).get("label"))
        unknown_count = max(0, len(all_faces) - known_count)
        self._stat_known.set_value(str(known_count))
        self._stat_unknown.set_value(str(unknown_count))

        known = next((face for face in all_faces if (face.get("match") or {}).get("label")), None)
        self._stat_last.set_value((known.get("match") or {}).get("label") if known else "-")

        if all_faces:
            labels = []
            for face in all_faces[:8]:
                match = face.get("match") or {}
                labels.append(match.get("label") or "Unknown")
            self._faces_label.setText(", ".join(labels))
        else:
            self._faces_label.setText("No faces detected yet")
        self._alert_for_unknown_faces(camera_statuses)

    def _all_current_faces(self, camera_statuses: list[dict]) -> list[dict]:
        faces: list[dict] = []
        for camera in camera_statuses:
            faces.extend(camera.get("lastFaces") or [])
        return faces or (self._backend_status.get("lastFaces") or [])

    def _camera_faces(self, camera_id: str) -> list[dict]:
        camera = next((item for item in (self._backend_status.get("cameras") or []) if str(item.get("id")) == camera_id), None)
        camera_faces = (camera or {}).get("lastFaces") or []
        if camera_faces:
            return camera_faces

        # Older/running backend processes may only expose the latest detection
        # globally, which is how the browser live page draws its main overlay.
        running_cameras = [
            item for item in (self._backend_status.get("cameras") or [])
            if (item.get("stream") or {}).get("running")
        ]
        if len(running_cameras) <= 1 or str((running_cameras[0] if running_cameras else {}).get("id")) == camera_id:
            return self._backend_status.get("lastFaces") or []
        return []

    def _refresh_frames(self):
        if not self._feed_widgets:
            return
        for camera_id, feed in self._feed_widgets.items():
            frame = self.backend.frame(camera_id=camera_id)
            feed.set_frame(frame, self._camera_faces(camera_id))

    def _alert_for_unknown_faces(self, camera_statuses: list[dict]):
        now = int(time.time() * 1000)
        for camera in camera_statuses:
            camera_id = str(camera.get("id") or "camera")
            faces = camera.get("lastFaces") or []
            has_unknown = any(not (face.get("match") or {}).get("label") for face in faces)
            if not has_unknown:
                continue
            previous = int(self._last_unknown_alarm_at.get(camera_id) or 0)
            if now - previous < self._alarm_cooldown_ms:
                continue
            self._last_unknown_alarm_at[camera_id] = now
            if self._alarm_sound and self._alarm_sound.isLoaded():
                self._alarm_sound.stop()
                self._alarm_sound.play()
            else:
                QApplication.beep()

    def _create_alarm_sound(self) -> QSoundEffect | None:
        configured = os.getenv("FACEAGENT_UI_ALARM_SOUND") or os.getenv("ALARM_SOUND_PATH")
        alarm_path = Path(configured).expanduser() if configured else (
            Path(__file__).resolve().parents[2] / "python_recognizer" / "alarm.wav"
        )
        if not alarm_path.exists():
            return None

        sound = QSoundEffect(self)
        sound.setSource(QUrl.fromLocalFile(str(alarm_path)))
        sound.setVolume(float(os.getenv("FACEAGENT_UI_ALARM_VOLUME", "0.9")))
        return sound

    def _start_detection(self):
        camera_id = self.camera_selector.currentData()
        try:
            self.backend.start(camera_id=camera_id)
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            self._stat_state.set_value("Offline")
            self._faces_label.setText(f"Backend not reachable: {exc}")

    def _stop_detection(self):
        try:
            self.backend.stop()
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            self._stat_state.set_value("Offline")
            self._faces_label.setText(f"Backend not reachable: {exc}")

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
