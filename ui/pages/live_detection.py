"""Live Detection page with camera feed viewer for the FaceAgent app."""

import os
import sys
import time
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame,
    QPushButton, QComboBox, QGridLayout, QScrollArea, QDialog,
)
from PySide6.QtCore import QUrl, Qt, QTimer
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QSoundEffect

from ..widgets import StatCard, SectionHeader, Pill, EmptyState
from ..backend_client import BackendClient
from ..database import Database
from ..qt_workers import run_in_background


class CameraFeedWidget(QFrame):
    """Lightweight NVR-style widget showing an unannotated camera preview."""

    def __init__(self, camera: dict, frame_bytes: bytes | None = None, parent=None):
        super().__init__(parent)
        self.camera = camera
        self._single_camera_mode = False
        self._last_pixmap = QPixmap()
        self._stream_manager = QNetworkAccessManager(self)
        self._stream_reply = None
        self._stream_buffer = bytearray()
        self._stream_base_url = ""
        self._stream_stopped = False
        self.setStyleSheet("""
            CameraFeedWidget {
                background: #050b14;
                border: 1px solid rgba(155, 173, 200, 0.18);
                border-radius: 10px;
            }
        """)
        self.setMinimumSize(280, 220)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        # Camera name / role header
        header = QHBoxLayout()
        header.setSpacing(8)
        name_label = QLabel(camera.get("name", "Camera"))
        name_label.setToolTip(camera.get("rtsp_url", ""))
        name_label.setStyleSheet("color: #f8fafc; font-size: 15px; font-weight: 700; background: transparent;")
        header.addWidget(name_label)

        role = camera.get("camera_role", "general")
        role_pill = Pill(role.capitalize(), "sync" if role != "general" else "idle")
        header.addWidget(role_pill)
        header.addStretch()

        self.status_pill = Pill("Checking…", "warning")
        header.addWidget(self.status_pill)
        layout.addLayout(header)

        # Placeholder for stream area
        self.feed_label = QLabel("Checking camera connection…")
        self.feed_label.setAlignment(Qt.AlignCenter)
        self.feed_label.setMinimumHeight(220)
        self.feed_label.setStyleSheet("""
            color: #6b7d9a;
            font-size: 14px;
            background: rgba(0,0,0,0.3);
            border-radius: 8px;
        """)
        layout.addWidget(self.feed_label, 1)

        # Stream metadata footer
        footer = QHBoxLayout()
        footer.setSpacing(8)
        url_label = QLabel(camera.get("rtsp_url", "No URL"))
        url_label.setStyleSheet("color: #94a3b8; font-size: 11px; background: transparent;")
        url_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        # footer.addWidget(url_label, 1)
        self.frame_info = QLabel("Waiting for frame")
        self.frame_info.setStyleSheet("color: #64748b; font-size: 10px; background: transparent;")
        footer.addWidget(self.frame_info)
        layout.addLayout(footer)

        self.set_frame(frame_bytes)

    def start_raw_stream(self, base_url: str) -> None:
        """Display raw MJPEG frames without detection overlays."""
        camera_id = str(self.camera.get("id") or "")
        if not camera_id or self._stream_reply is not None:
            return
        self._stream_stopped = False
        self._stream_base_url = base_url
        from urllib.parse import quote
        preview_fps = max(1, min(15, int(os.getenv("FACEAGENT_PREVIEW_FPS", "8"))))
        url = f"{base_url.rstrip('/')}/stream.mjpg?cameraId={quote(camera_id, safe='')}&fps={preview_fps}"
        reply = self._stream_manager.get(QNetworkRequest(QUrl(url)))
        self._stream_reply = reply
        reply.readyRead.connect(self._read_stream_data)
        reply.finished.connect(self._stream_finished)

    def _read_stream_data(self) -> None:
        if self._stream_reply is None:
            return
        self._stream_buffer.extend(bytes(self._stream_reply.readAll()))
        while True:
            start = self._stream_buffer.find(b"\xff\xd8")
            if start < 0:
                self._stream_buffer = self._stream_buffer[-1:]
                return
            end = self._stream_buffer.find(b"\xff\xd9", start + 2)
            if end < 0:
                if start:
                    del self._stream_buffer[:start]
                return
            frame = bytes(self._stream_buffer[start:end + 2])
            del self._stream_buffer[:end + 2]
            self.set_frame(frame)
            self.set_frame_info("Live now")

    def _stream_finished(self) -> None:
        reply = self._stream_reply
        self._stream_reply = None
        self._stream_buffer.clear()
        if reply is not None:
            reply.deleteLater()
        if not self.isHidden() and not self._stream_stopped:
            self.set_frame_info("Stream reconnecting")
            QTimer.singleShot(1000, lambda: self.start_raw_stream(self._stream_base_url))

    def stop_raw_stream(self) -> None:
        self._stream_stopped = True
        if self._stream_reply is not None:
            self._stream_reply.abort()
            self._stream_reply = None
        self._stream_buffer.clear()

    def update_faces(self, faces: list[dict]):
        # Detection results remain available to the page's counters, alarms,
        # and attendance logic, but are not painted over the camera preview.
        return

    def set_single_camera_mode(self, enabled: bool):
        self._single_camera_mode = enabled
        self._update_feed_height()

    def _update_feed_height(self):
        if not self._single_camera_mode or self._last_pixmap.isNull():
            return
        width = max(320, self.feed_label.width())
        aspect_height = int(width * self._last_pixmap.height() / max(1, self._last_pixmap.width()))
        self.feed_label.setMinimumHeight(max(220, aspect_height))

    def set_status(self, text: str, state: str = "idle", detail: str = ""):
        self.status_pill.set_text(text)
        self.status_pill.set_state(state)
        self.status_pill.setToolTip(detail)
        if self._last_pixmap.isNull():
            self.feed_label.setText(detail or text)
            self.feed_label.setPixmap(QPixmap())

    def set_frame_info(self, text: str):
        self.frame_info.setText(text)

    def set_frame(self, frame_bytes: bytes | None, faces: list[dict] | None = None):
        if not frame_bytes:
            return
        pixmap = QPixmap()
        if not pixmap.loadFromData(frame_bytes):
            return
        self._last_pixmap = pixmap
        self._update_feed_height()
        self._paint_frame()
        self.feed_label.setText("")

    def closeEvent(self, event):
        self.stop_raw_stream()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_feed_height()
        self._paint_frame()

    def _paint_frame(self):
        if self._last_pixmap.isNull():
            return

        target_size = self.feed_label.size()
        # Preserve the camera's native aspect ratio so the complete frame is
        # visible at every window size. Empty space is letterboxed rather than
        # stretching or cropping the footage.
        scaled = self._last_pixmap.scaled(target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        canvas = QPixmap(target_size)
        canvas.fill(QColor("#050b14"))

        painter = QPainter(canvas)
        offset_x = (target_size.width() - scaled.width()) // 2
        offset_y = (target_size.height() - scaled.height()) // 2
        painter.drawPixmap(offset_x, offset_y, scaled)

        # Keep the preview raw. Recognition continues independently in the
        # backend and its results are still used by business logic below the
        # camera grid (counters, alarms, attendance, and detected faces).
        painter.end()
        self.feed_label.setPixmap(canvas)
        return

class FullscreenCameraGrid(QDialog):
    """Camera-only live grid shown without the rest of the application UI."""

    def __init__(self, cameras: list[dict], backend: BackendClient, parent=None):
        super().__init__(parent)
        self.backend = backend
        self.cameras = cameras
        self.feeds: dict[str, CameraFeedWidget] = {}
        self.status_request_active = False
        self.page_size = max(1, int(os.getenv("FACEAGENT_FULLSCREEN_PAGE_SIZE", "9")))
        self.page_index = 0
        self.setWindowTitle("Otence Intelligence · Live Cameras")
        self.setStyleSheet("QDialog { background: #020617; }")
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        self.main_layout.addLayout(self.grid, 1)
        controls = QHBoxLayout()
        controls.addStretch()
        self.page_label = QLabel()
        self.page_label.setStyleSheet("color: #cbd5e1; font-size: 13px; font-weight: 700;")
        self.previous_button = QPushButton("‹ Previous")
        self.next_button = QPushButton("Next ›")
        for button in (self.previous_button, self.next_button):
            button.setMinimumWidth(110)
            button.setStyleSheet("QPushButton { background:#0f172a; color:#e2e8f0; border:1px solid #334155; border-radius:6px; padding:8px 14px; font-weight:700; } QPushButton:disabled { color:#64748b; border-color:#1e293b; }")
        self.previous_button.clicked.connect(lambda: self._change_page(-1))
        self.next_button.clicked.connect(lambda: self._change_page(1))
        controls.addWidget(self.page_label)
        controls.addSpacing(12)
        controls.addWidget(self.previous_button)
        controls.addWidget(self.next_button)
        self.main_layout.addLayout(controls)
        self._render_page()
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_status)
        self.status_timer.start(500)
        self.refresh_status()

    def _render_page(self) -> None:
        for feed in self.feeds.values():
            feed.stop_raw_stream()
            feed.deleteLater()
        self.feeds = {}
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        total_pages = max(1, (len(self.cameras) + self.page_size - 1) // self.page_size)
        self.page_index = max(0, min(self.page_index, total_pages - 1))
        visible = self.cameras[self.page_index * self.page_size:(self.page_index + 1) * self.page_size]
        columns = max(1, min(3, int(len(visible) ** 0.5) + (1 if int(len(visible) ** 0.5) ** 2 < len(visible) else 0)))
        for index, camera in enumerate(visible):
            feed = CameraFeedWidget(camera, parent=self)
            feed.set_single_camera_mode(True)
            feed.setMinimumSize(360, 260)
            camera_id = str(camera.get("id"))
            self.feeds[camera_id] = feed
            row, column = divmod(index, columns)
            self.grid.addWidget(feed, row, column)
            feed.start_raw_stream(self.backend.base_url)
        self.page_label.setText(f"Page {self.page_index + 1} of {total_pages} · {len(self.cameras)} cameras")
        self.previous_button.setEnabled(self.page_index > 0)
        self.next_button.setEnabled(self.page_index < total_pages - 1)

    def _change_page(self, delta: int) -> None:
        self.page_index += delta
        self._render_page()
        self.refresh_status()

    def refresh_frames(self):
        return

    def show_fullscreen(self):
        self.showFullScreen()

    def refresh_status(self):
        if self.status_request_active:
            return
        self.status_request_active = True
        run_in_background(
            self.backend.status,
            on_result=self._apply_status,
            on_finished=lambda: setattr(self, "status_request_active", False),
        )

    def _apply_status(self, status):
        by_id = {str(item.get("id") or "").split("::")[-1]: item for item in status.get("cameras", [])}
        for camera_id, feed in self.feeds.items():
            camera = by_id.get(str(camera_id).split("::")[-1]) or {}
            feed.update_faces(camera.get("lastFaces") or [])

    def closeEvent(self, event):
        for feed in self.feeds.values():
            feed.stop_raw_stream()
        self.status_timer.stop()
        super().closeEvent(event)


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
        self._status_request_active = False
        self._local_refresh_active = False
        self._start_request_active = False
        self._last_start_attempt_ms = 0
        self._frame_requests_active: set[str] = set()
        self._alarm_cooldown_ms = max(500, int(os.getenv("FACEAGENT_UI_ALARM_COOLDOWN_MS", "5000")))
        self._alarm_sound = self._create_alarm_sound()
        self._build_ui()
        self._startup_timer = QTimer(self)
        self._startup_timer.setInterval(2000)
        self._startup_timer.timeout.connect(self._ensure_detection_started)
        self._startup_timer.start()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_backend_status)
        self._refresh_timer.start(1000)
        self.refresh()
        QTimer.singleShot(1500, self._ensure_detection_started)

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
        desc = QLabel("Monitor camera health, recognition activity, and security events in real time")
        desc.setProperty("class", "page-desc")
        text_col.addWidget(title)
        text_col.addWidget(desc)
        hdr_layout.addLayout(text_col)
        hdr_layout.addStretch()
        self._system_pill = Pill("Checking system…", "warning")
        hdr_layout.addWidget(self._system_pill, 0, Qt.AlignVCenter)

        # Controls
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.camera_selector = QComboBox()
        self.camera_selector.setMinimumWidth(200)
        # controls.addWidget(self.camera_selector)

        # self.start_btn = QPushButton("Start Detection")
        # self.start_btn.setProperty("class", "primary")
        # self.start_btn.setStyleSheet("QPushButton { background:#1a73e8; color:#ffffff; border:1px solid #1a73e8; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { background:#1765cc; border-color:#1765cc; }")
        # self.start_btn.clicked.connect(self._start_detection)
        # controls.addWidget(self.start_btn)

        # self.stop_btn = QPushButton("Stop")
        # self.stop_btn.setStyleSheet("QPushButton { background:#ffffff; color:#111827; border:1px solid #e5e7eb; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { border-color:#1a73e8; background:#eef4ff; }")
        # self.stop_btn.clicked.connect(self._stop_detection)
        # controls.addWidget(self.stop_btn)

        self.refresh_btn = QPushButton("↻  Refresh")
        self.refresh_btn.setProperty("class", "ghost")
        self.refresh_btn.setToolTip("Refresh cameras and backend status")
        self.refresh_btn.setStyleSheet("QPushButton { background:#ffffff; color:#111827; border:1px solid #e5e7eb; border-radius:7px; padding:9px 16px; font-weight:700; } QPushButton:hover { border-color:#1a73e8; background:#eef4ff; }")
        self.refresh_btn.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_btn)
        self.fullscreen_btn = QPushButton("⛶  Full Screen")
        self.fullscreen_btn.setProperty("class", "ghost")
        self.fullscreen_btn.setToolTip("Show camera feeds only")
        self.fullscreen_btn.clicked.connect(self._open_fullscreen)
        controls.addWidget(self.fullscreen_btn)

        hdr_layout.addLayout(controls)
        layout.addWidget(header)

        # Status row
        self._sync_label = QLabel("Updating system status…")
        self._sync_label.setProperty("class", "muted")
        self._sync_label.setStyleSheet("font-size: 11px; padding-top: 2px;")
        layout.addWidget(self._sync_label)
        self._status_layout = QHBoxLayout()
        self._status_layout.setSpacing(12)
        self._stat_state = StatCard("State", "Idle")
        self._stat_known = StatCard("Known Detections", "0")
        self._stat_unknown = StatCard("Unknown Detections", "0")
        self._stat_registered = StatCard("Registered", "0")
        self._stat_cameras = StatCard("Cameras Online", "0/0")

        for card in [self._stat_state, self._stat_known, self._stat_unknown,
                     self._stat_registered, self._stat_cameras]:
            self._status_layout.addWidget(card)
        layout.addLayout(self._status_layout)

        # Camera grid
        layout.addWidget(SectionHeader("Camera Feeds", "Live connectivity and detection telemetry by camera"))
        self._camera_grid = QGridLayout()
        self._camera_grid.setSpacing(16)
        layout.addLayout(self._camera_grid)

        scroll.setWidget(self._container)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(scroll)

    def refresh(self):
        if self._local_refresh_active:
            return
        self._local_refresh_active = True
        self.refresh_btn.setEnabled(False)
        run_in_background(
            lambda: (self.db.list_cameras(), len(self.db.list_known_faces())),
            on_result=self._apply_local_state,
            on_error=self._handle_local_refresh_error,
            on_finished=self._finish_local_refresh,
        )

    def _apply_local_state(self, result):
        cameras, registered_count = result
        self._stat_registered.set_value(str(registered_count))
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
        for old_feed in self._feed_widgets.values():
            old_feed.stop_raw_stream()
            old_feed.deleteLater()
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
                feed.set_single_camera_mode(len(enabled) == 1)
                feed.start_raw_stream(self.backend.base_url)
                self._feed_widgets[str(cam.get("id"))] = feed
                row, col = divmod(idx, cols)
                self._camera_grid.addWidget(feed, row, col)
            self._refresh_frames()

    def _handle_local_refresh_error(self, exc: Exception):
        self._system_pill.set_text("UI data unavailable")
        self._system_pill.set_state("error")
        self._sync_label.setText(f"Unable to load camera configuration: {exc}")

    def _finish_local_refresh(self):
        self._local_refresh_active = False
        self.refresh_btn.setEnabled(True)

    def _open_fullscreen(self):
        cameras = [camera for camera in self.db.list_cameras() if camera.get("enabled")]
        if not cameras:
            self._sync_label.setText("No enabled cameras available for full-screen view")
            return
        dialog = FullscreenCameraGrid(cameras, self.backend, self)
        self._fullscreen_dialog = dialog
        dialog.show_fullscreen()
        dialog.exec()

    def _refresh_backend_status(self):
        if self._status_request_active:
            return
        self._status_request_active = True

        def on_status(status):
            self._backend_status = status
            self._render_backend_status()

        def on_error(exc):
            self._backend_status = {"state": "offline", "lastError": str(exc)}
            self._render_backend_status()

        run_in_background(
            self.backend.status,
            on_result=on_status,
            on_error=on_error,
            on_finished=lambda: setattr(self, "_status_request_active", False),
        )

    def _ensure_detection_started(self):
        """Retry startup after the backend has finished loading its model."""
        if self._start_request_active:
            return
        cameras = [camera for camera in self.db.list_cameras() if camera.get("enabled")]
        state = str(self._backend_status.get("state") or "").lower()
        now = int(time.time() * 1000)
        if not cameras or state in {"running", "starting"} or now - self._last_start_attempt_ms < 3000:
            return
        self._start_request_active = True
        self._last_start_attempt_ms = now
        self._backend_status = {
            **self._backend_status,
            "state": "starting",
        }
        self._render_backend_status()
        run_in_background(
            self.backend.start,
            on_result=lambda _result: self._on_detection_started(),
            on_error=lambda exc: self._show_backend_error(exc),
            on_finished=lambda: setattr(self, "_start_request_active", False),
        )

    def _on_detection_started(self):
        self._startup_timer.stop()
        self._refresh_backend_status()

    def _render_backend_status(self):

        cameras = self.db.list_cameras()
        enabled = [c for c in cameras if c.get("enabled")]
        if not enabled:
            state = "No Cameras"
        else:
            state = str(self._backend_status.get("state") or "offline").title()
        self._stat_state.set_value(state)
        system_state = str(self._backend_status.get("state") or "offline").lower()
        system_state_map = {
            "running": ("System live", "running"),
            "starting": ("Starting detection", "warning"),
            "offline": ("Backend offline", "error"),
        }
        system_text, system_badge_state = system_state_map.get(system_state, (state, "idle"))
        self._system_pill.set_text(system_text)
        self._system_pill.set_state(system_badge_state)
        self._sync_label.setText(f"Last updated {time.strftime('%H:%M:%S')} · Status refreshes automatically")

        camera_statuses = self._backend_status.get("cameras") or []

        def camera_key(value) -> str:
            # Backend status may expose tenant-scoped IDs while the local UI
            # database exposes the unscoped ID for the default tenant.
            return str(value or "").split("::")[-1]

        status_by_id = {camera_key(item.get("id")): item for item in camera_statuses}
        online_count = 0
        for camera_id, feed in self._feed_widgets.items():
            stream = (status_by_id.get(camera_key(camera_id)) or {}).get("stream") or {}
            running = bool(stream.get("running"))
            last_state = str(stream.get("lastState") or "").lower()
            error = str(stream.get("lastError") or "")
            age_ms = stream.get("ageMs")
            stale = age_ms is not None and int(age_ms) > 5000
            if running and not stale:
                online_count += 1
                feed.set_status("Live", "running", "Camera is connected and sending frames")
                feed.set_frame_info("Live now")
            elif last_state in {"error", "failed", "disconnected", "offline"} or error:
                detail = error or f"Stream state: {last_state or 'disconnected'}"
                feed.set_status("Disconnected", "error", detail)
                feed.set_frame_info("No current frame")
            elif running or last_state in {"starting", "connecting", "reconnecting"}:
                feed.set_status("Connecting…", "warning", "Waiting for the camera stream")
                feed.set_frame_info("Connecting")
            else:
                feed.set_status("Offline", "idle", "Camera is not currently streaming")
                feed.set_frame_info("Stream stopped")
            feed.update_faces(self._camera_faces(camera_id))
        self._stat_cameras.set_value(f"{online_count}/{len(self._feed_widgets)}")

        all_faces = self._all_current_faces(camera_statuses)
        known_count = sum(1 for face in all_faces if (face.get("match") or {}).get("label"))
        unknown_count = max(0, len(all_faces) - known_count)
        self._stat_known.set_value(str(known_count))
        self._stat_unknown.set_value(str(unknown_count))

        self._alert_for_unknown_faces(camera_statuses)

    def _all_current_faces(self, camera_statuses: list[dict]) -> list[dict]:
        faces: list[dict] = []
        for camera in camera_statuses:
            faces.extend(camera.get("lastFaces") or [])
        return faces or (self._backend_status.get("lastFaces") or [])

    def _camera_faces(self, camera_id: str) -> list[dict]:
        camera_key = str(camera_id or "").split("::")[-1]
        camera = next(
            (
                item for item in (self._backend_status.get("cameras") or [])
                if str(item.get("id") or "").split("::")[-1] == camera_key
            ),
            None,
        )
        camera_faces = (camera or {}).get("lastFaces") or []
        if camera_faces:
            return camera_faces

        # Older/running backend processes may only expose the latest detection
        # globally, which is how the browser live page draws its main overlay.
        running_cameras = [
            item for item in (self._backend_status.get("cameras") or [])
            if (item.get("stream") or {}).get("running")
        ]
        if len(running_cameras) <= 1 or str((running_cameras[0] if running_cameras else {}).get("id") or "").split("::")[-1] == camera_key:
            return self._backend_status.get("lastFaces") or []
        return []

    def _refresh_frames(self):
        # Preview tiles now consume one raw MJPEG connection each instead of
        # repeatedly polling /frame.jpg. Detection remains backend-controlled.
        return

    def _alert_for_unknown_faces(self, camera_statuses: list[dict]):
        now = int(time.time() * 1000)
        # Don't ring alarm if disabled in configuration
        alarm_enabled = self.db.get_setting("ALARM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
        if not alarm_enabled:
            return

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
            alarm_enabled = self.db.get_setting("ALARM_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
            if alarm_enabled:
                if self._alarm_sound and self._alarm_sound.isLoaded():
                    self._alarm_sound.stop()
                    self._alarm_sound.play()
                else:
                    QApplication.beep()

    def _create_alarm_sound(self) -> QSoundEffect | None:
        configured = os.getenv("FACEAGENT_UI_ALARM_SOUND") or os.getenv("ALARM_SOUND_PATH")
        if configured:
            alarm_path = Path(configured).expanduser()
        else:
            base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
            alarm_path = base / "python_recognizer" / "alarm.wav"
            if not alarm_path.exists():
                alarm_path = Path(__file__).resolve().parents[2] / "python_recognizer" / "alarm.wav"
        if not alarm_path.exists():
            return None

        sound = QSoundEffect(self)
        sound.setSource(QUrl.fromLocalFile(str(alarm_path)))
        sound.setVolume(float(os.getenv("FACEAGENT_UI_ALARM_VOLUME", "0.9")))
        return sound

    def _start_detection(self):
        camera_id = self.camera_selector.currentData()
        run_in_background(
            lambda: self.backend.start(camera_id=camera_id),
            on_result=lambda _result: self.refresh(),
            on_error=self._show_backend_error,
        )

    def _stop_detection(self):
        run_in_background(
            self.backend.stop,
            on_result=lambda _result: self.refresh(),
            on_error=self._show_backend_error,
        )

    def _show_backend_error(self, exc: Exception):
        self._stat_state.set_value("Offline")
        self._system_pill.set_text("Backend offline")
        self._system_pill.set_state("error")
        self._sync_label.setText("Unable to reach the detection service · Retry from Refresh")

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
