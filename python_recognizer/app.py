from __future__ import annotations

import asyncio
import base64
import csv
import json
import os
import platform
import shutil
import subprocess
import logging
import threading
import time
from urllib.parse import quote
from urllib.parse import unquote
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from io import StringIO
from collections import defaultdict
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import cv2
import numpy as np
from fastapi import FastAPI, Header, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from insightface.app import FaceAnalysis

try:
    cv2.setLogLevel(3)
except Exception:
    pass

os.environ.setdefault("NO_ALBUMENTATIONS_UPDATE", "1")

# Import lightweight store. Support both:
#   uvicorn python_recognizer.app:app  (from project root)
#   uvicorn app:app                    (from python_recognizer/)
try:
    from python_recognizer.store import (
        SQLiteStore,
        utc_now,
        iso_now,
        parse_float_env,
        parse_int_env,
        normalize_tenant_id,
        normalize_embedding,
        scope_key,
        unscope_key,
    )
except ModuleNotFoundError:
    from store import (  # type: ignore
        SQLiteStore,
        utc_now,
        iso_now,
        parse_float_env,
        parse_int_env,
        normalize_tenant_id,
        normalize_embedding,
        scope_key,
        unscope_key,
    )


logger = logging.getLogger("python_recognizer")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)


def decode_base64_image(image_base64: str) -> np.ndarray:
    if "," in image_base64 and image_base64.lower().lstrip().startswith("data:"):
        image_base64 = image_base64.split(",", 1)[1]
    try:
        payload = base64.b64decode(image_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid base64 image payload") from exc

    data = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Unable to decode image")
    return image


class JpegFrameExtractor:
    def __init__(self, max_frame_bytes: int = 6 * 1024 * 1024) -> None:
        self.max_frame_bytes = max_frame_bytes
        self._buffer = bytearray()
        self._in_frame = False

    def push(self, chunk: bytes) -> list[bytes]:
        frames: list[bytes] = []
        self._buffer.extend(chunk)
        while True:
            start = self._buffer.find(b"\xff\xd8")
            end = self._buffer.find(b"\xff\xd9", start + 2)
            if start == -1 or end == -1:
                if len(self._buffer) > self.max_frame_bytes:
                    self._buffer.clear()
                break
            frame = bytes(self._buffer[start : end + 2])
            del self._buffer[: end + 2]
            frames.append(frame)
        return frames

    def reset(self) -> None:
        self._buffer.clear()


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_vec = normalize_embedding(left)
    right_vec = normalize_embedding(right)
    if left_vec.size == 0 or right_vec.size == 0:
        return -1.0
    denominator = float(np.linalg.norm(left_vec) * np.linalg.norm(right_vec))
    if denominator <= 0:
        return -1.0
    return float(np.dot(left_vec, right_vec) / denominator)


@dataclass
class FaceSample:
    label: str
    embeddings: list[list[float]]
    updatedAt: str

    @property
    def sample_count(self) -> int:
        return len(self.embeddings)


@dataclass
class CameraWorker:
    camera_id: str
    stop_event: threading.Event
    thread: threading.Thread


@dataclass
class FFmpegStream:
    process: subprocess.Popen[bytes]
    extractor: JpegFrameExtractor



class FaceEngine:
    def __init__(self) -> None:
        app_dir = Path(__file__).resolve().parent
        self.snapshot_path = Path(os.getenv("SNAPSHOT_PATH", str(app_dir / "snapshots"))).expanduser()
        db_path = Path(os.getenv("PYTHON_DB_PATH", str(app_dir / "data" / "app.db"))).expanduser()
        self.store = SQLiteStore(db_path)
        self.default_tenant_id = normalize_tenant_id(os.getenv("DEFAULT_TENANT_ID", "default"))
        self.store.ensure_tenant(self.default_tenant_id, os.getenv("DEFAULT_TENANT_NAME", "Local Tenant"))

        self.match_threshold = parse_float_env(
            "PYTHON_MATCH_THRESHOLD",
            parse_float_env("MATCH_THRESHOLD", 0.45),
        )
        self.detection_threshold = parse_float_env(
            "PYTHON_DETECTION_THRESHOLD",
            parse_float_env("DETECTION_THRESHOLD", 0.5),
        )
        self.snapshot_cooldown_ms = parse_int_env("SNAPSHOT_COOLDOWN_MS", 10_000)
        self.det_size = (
            parse_int_env("INSIGHTFACE_DET_WIDTH", 640),
            parse_int_env("INSIGHTFACE_DET_HEIGHT", 640),
        )
        self.model_name = os.getenv("INSIGHTFACE_MODEL", "buffalo_l")
        self.model_dir = os.getenv("INSIGHTFACE_MODEL_DIR") or str(
            Path.home() / ".cache" / "insightface"
        )
        default_alarm = Path(__file__).resolve().with_name("alarm.wav")
        downloads_alarm = Path.home() / "Downloads" / "mixkit-data-scaner-2847.wav"
        configured_alarm = os.getenv("ALARM_SOUND_PATH")
        self.alarm_sound_path = Path(configured_alarm).expanduser() if configured_alarm else (default_alarm if default_alarm.exists() else downloads_alarm)
        self.alarm_cooldown_ms = parse_int_env("ALARM_COOLDOWN_MS", 10_000)
        self.alarm_enabled = os.getenv("ALARM_ENABLED", os.getenv("ALARM_FLAG", "true")).lower() in {"1", "true", "yes", "on"}
        self.alarm_unknown_frames = parse_int_env("ALARM_UNKNOWN_CONFIRMATION_FRAMES", 1)
        self.alarm_min_detection_confidence = parse_float_env("ALARM_MIN_DETECTION_CONFIDENCE", 0.72)
        self.alarm_immediate_unknown_confidence = parse_float_env("ALARM_IMMEDIATE_UNKNOWN_CONFIDENCE", 0.9)
        self.known_grace_ms = parse_int_env("KNOWN_GRACE_MS", 800)
        self.recognition_grace_ms = parse_int_env("RECOGNITION_GRACE_MS", 1_000)
        self.sync_enabled = os.getenv("SYNC_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        self.sync_endpoint_url = os.getenv("SYNC_ENDPOINT_URL", "").strip()
        self.sync_interval_ms = parse_int_env("SYNC_INTERVAL_MS", 5000)
        self._model_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._last_snapshot_at = 0.0
        self._model = self._load_model()
        self._sync_thread: threading.Thread | None = None
        self._sync_stop = threading.Event()
        self._camera_workers: dict[str, CameraWorker] = {}
        self._camera_workers_lock = threading.RLock()
        self._camera_frames: dict[str, dict[str, Any]] = {}
        self._camera_frames_lock = threading.RLock()
        self._camera_meta_cache: dict[str, dict[str, Any]] = {}
        self._registered_face_count = len(self.store.list_faces(self.default_tenant_id))
        self.auto_start_detection = os.getenv("AUTO_START_DETECTION", "true").lower() in {"1", "true", "yes", "on"}
        self._state = "idle"
        self._started_at: str | None = None
        self._stopped_at: str | None = None
        self._last_error: str | None = None
        self._last_detection: dict[str, Any] | None = None
        self._last_faces: list[dict[str, Any]] = []
        self._detection_count = 0
        self._camera_alarm_state: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "unknown_streak": 0,
                "last_known_at": 0.0,
                "last_alarm_at": 0.0,
                "last_unknown_signature": None,
                "last_unknown_at": 0.0,
                "last_unknown_confidence": 0.0,
                "suppress_alarm_until": 0.0,
            }
        )
        self._camera_identity_state: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "last_known_label": None,
                "last_known_confidence": 0.0,
                "last_known_at": 0.0,
            }
        )
        if self.sync_enabled and self.sync_endpoint_url:
            self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
            self._sync_thread.start()
        if self.auto_start_detection:
            threading.Thread(target=self._auto_start_cameras, daemon=True).start()

    def _load_model(self) -> FaceAnalysis:
        providers = [provider.strip() for provider in os.getenv("INSIGHTFACE_PROVIDERS", "CPUExecutionProvider").split(",") if provider.strip()]
        model = FaceAnalysis(name=self.model_name, root=self.model_dir, providers=providers)
        model.prepare(ctx_id=-1, det_size=self.det_size)
        return model

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "ready": True,
            "model": self.model_name,
            "faces": self._registered_face_count,
            "cameras": len(self.store.list_cameras(self.default_tenant_id)),
            "runningCameras": len(self._camera_workers),
            "alarmSoundAvailable": self.alarm_sound_path.exists(),
            "alarmEnabled": self.alarm_enabled,
            "alarmCooldownMs": self.alarm_cooldown_ms,
            "alarmUnknownFrames": self.alarm_unknown_frames,
            "alarmMinDetectionConfidence": self.alarm_min_detection_confidence,
            "alarmImmediateUnknownConfidence": self.alarm_immediate_unknown_confidence,
            "knownGraceMs": self.known_grace_ms,
            "recognitionGraceMs": self.recognition_grace_ms,
            "timestamp": iso_now(),
        }

    def status(self) -> dict[str, Any]:
        with self._camera_frames_lock:
            camera_frames = dict(self._camera_frames)
        with self._camera_workers_lock:
            running_ids = set(self._camera_workers.keys())
        cameras: list[dict[str, Any]] = []
        for camera_id, meta in self._camera_meta_cache.items():
            frame_state = dict(camera_frames.get(camera_id) or {})
            cameras.append(
                {
                    "id": camera_id,
                    "name": meta.get("name") or camera_id,
                    "role": meta.get("role") or "general",
                    "stream": {
                        "running": bool(frame_state.get("running")) or camera_id in running_ids,
                        "lastState": frame_state.get("lastState"),
                        "lastError": frame_state.get("lastError"),
                        "lastFrameAt": datetime.fromtimestamp(float(frame_state.get("latest_at") or 0.0), tz=timezone.utc).isoformat(timespec="milliseconds") if float(frame_state.get("latest_at") or 0.0) else None,
                    },
                    "busy": False,
                    "processedFrames": int(frame_state.get("processedFrames") or 0),
                    "droppedFrames": 0,
                    "lastFaces": frame_state.get("lastFaces") or [],
                    "lastDetection": frame_state.get("lastDetection"),
                }
            )
        return {
            "state": self._state,
            "startedAt": self._started_at,
            "stoppedAt": self._stopped_at,
            "lastError": self._last_error,
            "lastDetection": self._last_detection,
            "detectionCount": self._detection_count,
            "frames": {
                "received": 0,
                "accepted": 0,
                "detector": {
                    "ready": True,
                    "busy": False,
                    "droppedFrames": 0,
                    "processedFrames": 0,
                },
            },
            "config": {
                "snapshotPath": str(self.snapshot_path),
                "detectionThreshold": self.detection_threshold,
                "matchThreshold": self.match_threshold,
                "frameRate": parse_int_env("FRAME_RATE", 2),
                "streamFrameRate": parse_int_env("STREAM_FRAME_RATE", 10),
                "cooldownMs": self.snapshot_cooldown_ms,
                "recognitionBackend": "python",
                "pythonRecognizerUrl": None,
            },
            "stream": {"running": bool(self._camera_workers), "lastState": None},
            "lastFaces": self._last_faces,
            "registeredFaces": self._registered_face_count,
            "attendanceCount": 0,
            "cameras": cameras,
            "update": {"enabled": False},
        }

    def alarm_sound(self) -> Path | None:
        if self.alarm_sound_path.exists():
            return self.alarm_sound_path
        return None

    def recognize(
        self,
        image: np.ndarray,
        camera_role: str = "general",
        camera_id: str | None = None,
        tenant_id: str | None = None,
        camera_department_id: str | None = None,
    ) -> dict[str, Any]:
        tenant = tenant_id or self.default_tenant_id
        with self._model_lock:
            faces = self._model.get(image)

        detected = [self._serialize_face(face, camera_department_id) for face in self._filter_faces(faces)]
        detected = self._stabilize_camera_faces(detected, camera_role, camera_id)
        self._last_faces = detected
        self._detection_count += 1
        snapshot = self._maybe_save_snapshot(image, detected)
        state = "faces detected" if detected else "no face detected"
        camera_key = camera_id or camera_role or "general"
        known_faces = [face for face in detected if face["match"] and face["match"].get("label")]
        unknown_faces = [face for face in detected if not face["match"] or not face["match"].get("label")]
        unknown_faces = [face for face in unknown_faces if float(face.get("confidence") or 0.0) >= self.alarm_min_detection_confidence]
        unknown_faces = [face for face in unknown_faces if self._is_alertworthy_face(face, image.shape)]
        if unknown_faces:
            snapshot = self._maybe_save_snapshot(image, detected, force=True, reason="unknown")
        if camera_role in {"check_in", "check_out"} and known_faces:
            snapshot = self._maybe_save_snapshot(image, detected, force=True, reason=camera_role)
        if snapshot is not None:
            state = "snapshot saved"
            self._last_detection = snapshot
        self._update_camera_alarm_state(camera_key, known_faces, unknown_faces)
        should_alarm = self._should_alarm_camera(camera_key, unknown_faces)
        camera_record = self.store.get_camera(camera_id, tenant) if camera_id else None
        camera_name = str(camera_record.get("name") or "") if camera_record else None
        if unknown_faces:
            now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0
            last_logged = float(self._camera_alarm_state[camera_key].get("last_logged_alarm_at") or 0.0)
            # De-duplicate alarm logging: log 1 single alarm record per 5 seconds per camera
            if now_ms - last_logged >= 5000.0:
                self._camera_alarm_state[camera_key]["last_logged_alarm_at"] = now_ms
                alarm_record = {
                    "reason": "unknown_person",
                    "cameraRole": camera_role,
                    "cameraId": camera_id,
                    "cameraName": camera_name,
                    "timestamp": iso_now(),
                    "faces": unknown_faces,
                    "snapshot": snapshot,
                }
                self.store.enqueue_sync_event("alarm.triggered", alarm_record)
            if self.alarm_enabled and should_alarm:
                self._trigger_alarm(
                    image,
                    camera_role,
                    camera_id,
                    "unknown_person",
                    unknown_faces,
                    snapshot,
                    camera_name,
                )
        effective_department_id = camera_department_id or (str(camera_record.get("department_id") or "") if camera_record else "")
        department_record = self.store.get_department(effective_department_id, tenant) if effective_department_id else None
        department_name = str(department_record.get("name") or "") if department_record else None
        snapshot_path = str(snapshot.get("path")) if snapshot and snapshot.get("path") else None
        for face in known_faces:
            if face["match"] and face["match"].get("label"):
                self.store.record_attendance(
                    str(face["match"]["label"]),
                    float(face["match"]["confidence"]),
                    iso_now(),
                    self.snapshot_cooldown_ms,
                    camera_role,
                    tenant,
                    camera_id,
                    camera_name,
                    effective_department_id or None,
                    department_name,
                    snapshot_path,
                )
                self.store.enqueue_sync_event(
                    "attendance.recorded",
                    {
                        "label": str(face["match"]["label"]),
                        "confidence": float(face["match"]["confidence"]),
                        "timestamp": iso_now(),
                        "cameraRole": camera_role,
                        "cameraId": camera_id,
                        "cameraName": camera_name,
                        "departmentId": effective_department_id or None,
                        "departmentName": department_name,
                        "snapshot": snapshot,
                    },
                    tenant,
                )
        return {
            "state": state,
            "faces": detected,
            "snapshot": snapshot,
        }

    def register(
        self,
        label: str,
        image: np.ndarray,
        camera_role: str = "general",
        camera_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        label = label.strip()
        if not label:
            raise HTTPException(status_code=400, detail="Label is required")
        tenant = tenant_id or self.default_tenant_id

        with self._model_lock:
            faces = self._filter_faces(self._model.get(image))

        if not faces:
            raise HTTPException(status_code=400, detail="No face found in the current frame.")

        face = max(faces, key=lambda item: float(item.bbox[2] - item.bbox[0]) * float(item.bbox[3] - item.bbox[1]) * float(getattr(item, "det_score", 0.0)))
        embedding = self._embedding_for(face)
        if embedding is None:
            raise HTTPException(status_code=400, detail="Face embedding could not be generated.")

        sample = self.store.register_face(label, embedding, tenant)
        self._registered_face_count = len(self.store.list_faces(self.default_tenant_id))
        self.store.enqueue_sync_event(
            "face.registered",
            {
                "label": sample["label"],
                "sampleCount": sample["sampleCount"],
                "updatedAt": sample["updated_at"],
                "cameraRole": camera_role,
                "cameraId": camera_id,
            },
            tenant,
        )
        return {
            "label": sample["label"],
            "sampleCount": sample["sampleCount"],
            "updatedAt": sample["updated_at"],
        }

    def latest_frame_image(self, camera_id: str | None = None, camera_role: str | None = None) -> np.ndarray | None:
        camera = self.stream_camera(camera_id, camera_role)
        if camera is None:
            return None
        with self._camera_frames_lock:
            state = dict(self._camera_frames.get(str(camera["id"])) or {})
        frame_bytes = state.get("latest_frame")
        if not frame_bytes:
            return None
        frame_array = np.frombuffer(frame_bytes, dtype=np.uint8)
        return cv2.imdecode(frame_array, cv2.IMREAD_COLOR)

    def latest_detectable_frame(self) -> np.ndarray | None:
        cameras = self._resolve_cameras()
        for camera in cameras:
            frame = self.latest_frame_image(str(camera.get("id") or ""), str(camera.get("camera_role") or "general"))
            if frame is None:
                continue
            with self._model_lock:
                faces = self._filter_faces(self._model.get(frame))
            if faces:
                return frame
        return None

    def list_faces(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_faces(tenant_id or self.default_tenant_id)

    def remove_face(self, label: str, tenant_id: str | None = None) -> bool:
        removed = self.store.remove_face(label, tenant_id or self.default_tenant_id)
        if removed:
            self._registered_face_count = max(0, self._registered_face_count - 1)
        return removed

    def clear_faces(self, tenant_id: str | None = None) -> None:
        tenant = tenant_id or self.default_tenant_id
        self.store.clear_faces(tenant)
        self._registered_face_count = 0
        self.store.enqueue_sync_event("faces.cleared", {}, tenant)

    def list_cameras(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_cameras(tenant_id or self.default_tenant_id)

    def list_departments(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_departments(tenant_id or self.default_tenant_id)

    def upsert_department(self, payload: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        return self.store.upsert_department(payload, tenant_id or self.default_tenant_id)

    def delete_department(self, department_id: str, tenant_id: str | None = None) -> bool:
        return self.store.delete_department(department_id, tenant_id or self.default_tenant_id)

    def list_employees(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_employees(tenant_id or self.default_tenant_id)

    def upsert_employee(self, payload: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        return self.store.upsert_employee(payload, tenant_id or self.default_tenant_id)

    def delete_employee(self, employee_id: str, tenant_id: str | None = None) -> bool:
        removed = self.store.delete_employee(employee_id, tenant_id or self.default_tenant_id)
        self._registered_face_count = len(self.store.list_faces(self.default_tenant_id))
        return removed

    def cleanup_orphan_faces(self, tenant_id: str | None = None) -> dict[str, Any]:
        removed = self.store.cleanup_orphan_faces(tenant_id or self.default_tenant_id)
        self._registered_face_count = len(self.store.list_faces(self.default_tenant_id))
        return {"ok": True, "removed": removed, "registeredFaces": self._registered_face_count}

    def register_employee_photos(self, employee_id: str, images: list[np.ndarray], tenant_id: str | None = None) -> dict[str, Any]:
        tenant = tenant_id or self.default_tenant_id
        employee = next((item for item in self.store.list_employees(tenant) if str(item["id"]) == employee_id), None)
        if employee is None:
            raise HTTPException(status_code=404, detail="Employee not found")
        added = 0
        for image in images:
            with self._model_lock:
                faces = self._filter_faces(self._model.get(image))
            if not faces:
                continue
            face = max(faces, key=lambda item: float(item.bbox[2] - item.bbox[0]) * float(item.bbox[3] - item.bbox[1]) * float(getattr(item, "det_score", 0.0)))
            embedding = self._embedding_for(face)
            if embedding is None:
                continue
            self.store.register_face(str(employee["name"]), embedding, tenant, employee_id)
            added += 1
        if added == 0:
            raise HTTPException(status_code=400, detail="No usable face found in uploaded photos")
        self._registered_face_count = len(self.store.list_faces(self.default_tenant_id))
        return {"ok": True, "employeeId": employee_id, "added": added}

    def get_camera(self, camera_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        return self.store.get_camera(camera_id, tenant_id or self.default_tenant_id)

    def upsert_camera(self, payload: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        return self.store.upsert_camera(payload, tenant_id or self.default_tenant_id)

    def delete_camera(self, camera_id: str, tenant_id: str | None = None) -> bool:
        return self.store.delete_camera(camera_id, tenant_id or self.default_tenant_id)

    def default_camera(self, tenant_id: str | None = None) -> dict[str, Any] | None:
        return self.store.get_default_camera(tenant_id or self.default_tenant_id)

    def list_attendance(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        return self.store.list_attendance(tenant_id or self.default_tenant_id)

    def stream_camera(self, camera_id: str | None = None, camera_role: str | None = None) -> dict[str, Any] | None:
        cameras = self._resolve_cameras(camera_id, camera_role)
        return cameras[0] if cameras else None

    def sync_status(self) -> dict[str, Any]:
        return {
            "enabled": self.sync_enabled,
            "endpointUrl": self.sync_endpoint_url or None,
            "pending": len(self.store.list_sync_events(1_000)),
            "running": bool(self._sync_thread and self._sync_thread.is_alive()),
        }

    def sync_now(self) -> dict[str, Any]:
        return self._flush_sync_queue()

    def start(self, camera_id: str | None = None, camera_role: str | None = None) -> dict[str, Any]:
        cameras = self._resolve_cameras(camera_id, camera_role)
        self._restart_camera_workers(cameras)
        self._state = "running"
        self._started_at = iso_now()
        self._stopped_at = None
        return {"ok": True, "runningCameras": len(cameras)}

    def stop(self) -> dict[str, Any]:
        self._stop_camera_workers()
        self._state = "idle"
        self._stopped_at = iso_now()
        return {"ok": True}

    def _resolve_cameras(self, camera_id: str | None = None, camera_role: str | None = None) -> list[dict[str, Any]]:
        cameras = [camera for camera in self.store.list_cameras(self.default_tenant_id) if int(camera.get("enabled", 1)) == 1]
        if camera_role:
            cameras = [camera for camera in cameras if str(camera.get("camera_role") or "general") == camera_role]
        if camera_id:
            cameras = [camera for camera in cameras if str(camera.get("id")) == camera_id]
        return cameras

    def _restart_camera_workers(self, cameras: list[dict[str, Any]]) -> None:
        self._camera_meta_cache = {
            str(camera["id"]): {
                "name": str(camera.get("name") or camera["id"]),
                "role": str(camera.get("camera_role") or "general"),
            }
            for camera in cameras
        }
        self._stop_camera_workers()
        for camera in cameras:
            self._start_camera_worker(camera)

    def _stop_camera_workers(self) -> None:
        with self._camera_workers_lock:
            workers = list(self._camera_workers.values())
            self._camera_workers.clear()
        for worker in workers:
            worker.stop_event.set()
            worker.thread.join(timeout=5)
        with self._camera_frames_lock:
            for state in self._camera_frames.values():
                state["running"] = False
                state["lastState"] = state.get("lastState") or "stopped"

    def _start_camera_worker(self, camera: dict[str, Any]) -> None:
        camera_id = str(camera["id"])
        stop_event = threading.Event()
        thread = threading.Thread(target=self._camera_worker_loop, args=(camera, stop_event), daemon=True)
        with self._camera_workers_lock:
            self._camera_workers[camera_id] = CameraWorker(camera_id=camera_id, stop_event=stop_event, thread=thread)
        with self._camera_frames_lock:
            self._camera_frames[camera_id] = {
                "latest_frame": None,
                "latest_at": 0.0,
                "running": True,
                "lastState": "starting",
                "lastError": None,
                "lastFaces": [],
                "lastDetection": None,
                "processedFrames": 0,
            }
        thread.start()

    def _camera_worker_loop(self, camera: dict[str, Any], stop_event: threading.Event) -> None:
        rtsp_url = self._normalize_rtsp_url(camera)
        if not rtsp_url:
            return

        camera_role = str(camera.get("camera_role") or "general")
        camera_id = str(camera.get("id") or "")
        camera_department_id = str(camera.get("department_id") or "")
        frame_rate = max(1, parse_int_env("STREAM_FRAME_RATE", 10))
        retry_delay = 1.0
        transport_cycle = ["tcp", "udp"]
        transport_index = 0
        consecutive_failures = 0
        while not stop_event.is_set():
            transport = transport_cycle[transport_index % len(transport_cycle)]
            stream = self._spawn_ffmpeg_stream(rtsp_url, frame_rate, transport)
            if stream is None:
                consecutive_failures += 1
                transport_index += 1
                logger.warning("Failed to open RTSP stream: %s", {"cameraId": camera_id, "rtspUrl": rtsp_url, "transport": transport})
                self._set_camera_frame_state(
                    camera_id,
                    running=False,
                    last_state=f"failed to open stream ({transport})",
                    last_error="failed to open stream",
                )
                self._camera_alarm_state[camera_id]["suppress_alarm_until"] = time.time() * 1000.0 + min(60_000, 5_000 * consecutive_failures)
                time.sleep(min(30.0, retry_delay * consecutive_failures))
                continue

            self._set_camera_frame_state(camera_id, running=True, last_state="stream connected", last_error=None)
            self._camera_alarm_state[camera_id]["suppress_alarm_until"] = time.time() * 1000.0 + 2_000
            latest_frame_box: dict[str, bytes | None] = {"frame": None}
            latest_lock = threading.Lock()

            def reader_loop() -> None:
                try:
                    while not stop_event.is_set() and stream.process.poll() is None:
                        chunk = stream.process.stdout.read(8192) if stream.process.stdout else b""
                        if not chunk:
                            time.sleep(0.01)
                            continue
                        frames = stream.extractor.push(chunk)
                        if not frames:
                            continue
                        with latest_lock:
                            latest_frame_box["frame"] = frames[-1]
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Camera reader failed: %s", {"cameraId": camera_id, "err": str(exc)})

            reader = threading.Thread(target=reader_loop, daemon=True)
            reader.start()
            try:
                while not stop_event.is_set():
                    if stream.process.poll() is not None:
                        exit_reason = self._drain_ffmpeg_stderr(stream, camera_id)
                        if exit_reason and "Host is down" in exit_reason:
                            transport_index += 1
                            consecutive_failures += 1
                        else:
                            consecutive_failures = 0
                        self._set_camera_frame_state(
                            camera_id,
                            running=False,
                            last_state=f"ffmpeg exited {stream.process.returncode}",
                            last_error=exit_reason or "ffmpeg exited",
                        )
                        break
                    with latest_lock:
                        latest_frame = latest_frame_box["frame"]
                    if latest_frame is None:
                        time.sleep(0.01)
                        continue
                    self._set_camera_frame_state(
                        camera_id,
                        running=True,
                        last_state="streaming",
                        latest_frame=latest_frame,
                        last_error=None,
                    )
                    frame_array = np.frombuffer(latest_frame, dtype=np.uint8)
                    frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                    if frame is None:
                        time.sleep(0.005)
                        continue
                    try:
                        result = self.recognize(frame, camera_role, camera_id, self.default_tenant_id, camera_department_id)
                        self._set_camera_frame_state(
                            camera_id,
                            last_faces=result.get("faces") or [],
                            last_detection=result.get("snapshot"),
                            increment_processed=True,
                        )
                        logger.debug("Frame processed: %s", {"cameraId": camera_id, "state": result.get("state")})
                    except Exception as exc:  # noqa: BLE001
                        self._set_camera_frame_state(camera_id, increment_processed=True)
                        logger.warning("Camera frame processing failed: %s", {"cameraId": camera_id, "err": str(exc)})
                    time.sleep(max(0.0, 1.0 / float(frame_rate)))
            finally:
                self._terminate_ffmpeg_stream(stream)
                reader.join(timeout=2)
                self._set_camera_frame_state(camera_id, running=False, last_state="reconnecting")
                self._camera_alarm_state[camera_id]["suppress_alarm_until"] = time.time() * 1000.0 + 3_000
                time.sleep(min(10.0, retry_delay * max(1, consecutive_failures)))

    def _inject_rtsp_credentials(self, rtsp_url: str, username: str, password: str) -> str:
        try:
            if rtsp_url.startswith("rtsp://"):
                without_scheme = rtsp_url[len("rtsp://") :]
                return f"rtsp://{quote(username, safe='')}:{quote(password, safe='')}@{without_scheme}"
        except Exception:
            return rtsp_url
        return rtsp_url

    def _normalize_rtsp_url(self, camera: dict[str, Any]) -> str:
        raw = str(camera.get("rtsp_url") or "").strip()
        if not raw:
            return ""

        parsed = urlsplit(raw)
        if parsed.scheme != "rtsp":
            return raw

        username = str(camera.get("rtsp_username") or unquote(parsed.username or "") or "").strip()
        password = str(camera.get("rtsp_password") or unquote(parsed.password or "") or "").strip()
        hostname = parsed.hostname or ""
        if not hostname:
            return raw

        netloc = hostname
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        if username:
            netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{netloc}"

        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    def _spawn_ffmpeg_stream(self, rtsp_url: str, frame_rate: int, transport: str = "tcp") -> FFmpegStream | None:
        ffmpeg_path = os.getenv("FFMPEG_PATH", "ffmpeg").strip() or "ffmpeg"
        args = [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "info",
            "-rtsp_transport",
            transport,
            "-thread_queue_size",
            "8",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-avioflags",
            "direct",
            "-analyzeduration",
            "0",
            "-probesize",
            "32",
            "-max_delay",
            "0",
            "-i",
            rtsp_url,
            "-an",
            "-sn",
            "-dn",
            "-q:v",
            "4",
            "-r",
            str(max(1, frame_rate)),
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
        try:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0)
        except Exception as exc:  # noqa: BLE001
            logger.warning("FFmpeg spawn failed: %s", exc)
            return None
        return FFmpegStream(process=process, extractor=JpegFrameExtractor())

    def _set_camera_frame_state(
        self,
        camera_id: str,
        *,
        running: bool | None = None,
        last_state: str | None = None,
        latest_frame: bytes | None = None,
        last_error: str | None = None,
        last_faces: list[dict[str, Any]] | None = None,
        last_detection: dict[str, Any] | None = None,
        increment_processed: bool = False,
    ) -> None:
        with self._camera_frames_lock:
            state = self._camera_frames.setdefault(
                camera_id,
                {
                    "latest_frame": None,
                    "latest_at": 0.0,
                    "running": False,
                    "lastState": None,
                    "lastError": None,
                    "lastFaces": [],
                    "lastDetection": None,
                    "processedFrames": 0,
                },
            )
            if running is not None:
                state["running"] = running
            if last_state is not None:
                state["lastState"] = last_state
            if latest_frame is not None:
                state["latest_frame"] = latest_frame
                state["latest_at"] = time.time()
            if last_error is not None:
                state["lastError"] = last_error
            if last_faces is not None:
                state["lastFaces"] = last_faces
            if last_detection is not None:
                state["lastDetection"] = last_detection
            if increment_processed:
                state["processedFrames"] = int(state.get("processedFrames") or 0) + 1

    def _camera_status_snapshot(self, camera_id: str) -> dict[str, Any]:
        with self._camera_frames_lock:
            state = dict(self._camera_frames.get(
                camera_id,
                {
                    "running": False,
                    "lastState": None,
                    "lastError": None,
                    "latest_at": 0.0,
                },
            ))
        latest_at = float(state.get("latest_at") or 0.0)
        latest_frame_at = datetime.fromtimestamp(latest_at, tz=timezone.utc).isoformat(timespec="milliseconds") if latest_at else None
        return {
            "running": bool(state.get("running")),
            "lastState": state.get("lastState"),
            "lastError": state.get("lastError"),
            "lastFrameAt": latest_frame_at,
            "ageMs": int(max(0.0, time.time() - latest_at) * 1000.0) if latest_at else None,
        }

    def _terminate_ffmpeg_stream(self, stream: FFmpegStream) -> None:
        process = stream.process
        try:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except Exception:
                    process.kill()
        finally:
            stream.extractor.reset()

    def _drain_ffmpeg_stderr(self, stream: FFmpegStream, camera_id: str) -> str | None:
        stderr = stream.process.stderr
        if stderr is None:
            return None
        try:
            output = stderr.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return None
        if output:
            short = output.splitlines()[-1][:500]
            logger.warning("FFmpeg exited for camera %s: %s", camera_id, short)
            return short
        return None

    def _auto_start_cameras(self) -> None:
        try:
            self.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Auto-start cameras failed: %s", exc)

    def _filter_faces(self, faces: list[Any]) -> list[Any]:
        filtered = []
        for face in faces:
            if float(getattr(face, "det_score", 0.0)) < self.detection_threshold:
                continue
            if self._embedding_for(face) is None:
                continue
            filtered.append(face)
        return filtered

    def _embedding_for(self, face: Any) -> np.ndarray | None:
        embedding = getattr(face, "normed_embedding", None)
        if embedding is None:
            embedding = getattr(face, "embedding", None)
        if embedding is None:
            return None
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size == 0:
            return None
        return normalize_embedding(vector)

    def _serialize_face(self, face: Any, camera_department_id: str | None = None) -> dict[str, Any]:
        embedding = self._embedding_for(face)
        assert embedding is not None
        raw_match = self._match_embedding(embedding, camera_department_id)
        match = raw_match
        bbox = [float(value) for value in getattr(face, "bbox", [0, 0, 0, 0])]
        x1, y1, x2, y2 = bbox[:4]
        confidence = float(getattr(face, "det_score", 0.0))
        return {
            "confidence": confidence,
            "box": {
                "x": x1,
                "y": y1,
                "width": max(0.0, x2 - x1),
                "height": max(0.0, y2 - y1),
            },
            "match": match,
            "rawMatch": raw_match,
        }

    def _is_alertworthy_face(self, face: dict[str, Any], shape: tuple[int, ...]) -> bool:
        if len(shape) < 2:
            return True
        height, width = int(shape[0]), int(shape[1])
        box = face.get("box") or {}
        x = float(box.get("x") or 0.0)
        y = float(box.get("y") or 0.0)
        w = float(box.get("width") or 0.0)
        h = float(box.get("height") or 0.0)
        if w < 60 or h < 60:
            return False
        if x < 0 or y < 0:
            return False
        if x + w > width or y + h > height:
            return False
        return True

    def _match_embedding(self, embedding: np.ndarray, camera_department_id: str | None = None) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        groups: dict[str, list[tuple[np.ndarray, str | None, list[str], bool]]] = {}
        for label, sample_embedding, _updated_at, _sample_count, employee_id, department_ids, employee_active in self.store.all_embeddings():
            groups.setdefault(label, []).append((sample_embedding, employee_id, department_ids, employee_active))

        for label, samples in groups.items():
            scores = [cosine_similarity(embedding, sample[0]) for sample in samples]
            if not scores:
                continue
            scores.sort(reverse=True)
            top_scores = scores[:3]
            score = max(top_scores[0], sum(top_scores) / len(top_scores))
            employee_id = next((sample[1] for sample in samples if sample[1]), None)
            department_ids = sorted({department_id for sample in samples for department_id in sample[2]})
            active = all(sample[3] for sample in samples)
            authorized = True
            if employee_id and camera_department_id and department_ids:
                authorized = camera_department_id in department_ids
            if not active:
                authorized = False
            if best is None or score > float(best["score"]):
                best = {
                    "label": label,
                    "score": score,
                    "confidence": score,
                    "sampleCount": len(samples),
                    "employeeId": employee_id,
                    "departmentIds": department_ids,
                    "authorized": authorized,
                }

        if best is None or float(best["score"]) < self.match_threshold:
            return None
        return best

    def _maybe_save_snapshot(
        self,
        image: np.ndarray,
        faces: list[dict[str, Any]],
        *,
        force: bool = False,
        reason: str = "face",
    ) -> dict[str, Any] | None:
        if not faces:
            return None

        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0
        with self._snapshot_lock:
            if not force and now_ms - self._last_snapshot_at < self.snapshot_cooldown_ms:
                return None

        best_face = max(faces, key=lambda face: float(face.get("confidence") or 0.0))
        timestamp = iso_now().replace(":", "-").replace("+", "-")
        filename = f"{reason}-{timestamp}.jpg"
        path = self.snapshot_path / filename
        self.snapshot_path.mkdir(parents=True, exist_ok=True)

        # Annotate bounding boxes around known and unknown faces
        annotated = image.copy()
        for face in faces:
            box = face.get("box") or {}
            x = int(box.get("x") or 0)
            y = int(box.get("y") or 0)
            w = int(box.get("width") or box.get("w") or 0)
            h = int(box.get("height") or box.get("h") or 0)
            if w <= 0 or h <= 0:
                continue

            match = face.get("match") or {}
            is_known = bool(match and match.get("label"))

            if is_known:
                # Green box for known employee
                color = (0, 200, 0)
                label_name = str(match.get("label"))
                if "::" in label_name:
                    parts = label_name.split("::")
                    if len(parts) >= 2:
                        label_name = parts[1]
                label_text = f"{label_name} ({float(face.get('confidence') or 0.0):.0%})"
            else:
                # Red box for unknown person
                color = (0, 0, 220)
                label_text = f"UNKNOWN ({float(face.get('confidence') or 0.0):.0%})"

            # Draw face rectangle
            cv2.rectangle(annotated, (x, y), (x + w, y + h), color, 2)

            # Draw background banner for label text
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.55
            thickness = 1
            (text_w, text_h), baseline = cv2.getTextSize(label_text, font, font_scale, thickness)
            banner_y1 = max(0, y - text_h - 8)
            banner_y2 = y
            cv2.rectangle(annotated, (x, banner_y1), (x + text_w + 10, banner_y2), color, -1)

            # Draw label text
            cv2.putText(
                annotated,
                label_text,
                (x + 5, max(text_h + 2, y - 4)),
                font,
                font_scale,
                (255, 255, 255),
                thickness,
                cv2.LINE_AA,
            )

        ok = cv2.imwrite(str(path), annotated)
        if not ok:
            return None
        with self._snapshot_lock:
            self._last_snapshot_at = now_ms
        return {
            "path": str(path),
            "timestamp": iso_now(),
            "confidence": float(best_face.get("confidence") or 0.0),
        }

    def _trigger_alarm(
        self,
        image: np.ndarray,
        camera_role: str,
        camera_id: str | None,
        reason: str,
        faces: list[dict[str, Any]],
        snapshot: dict[str, Any] | None,
        camera_name: str | None = None,
    ) -> None:
        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0
        camera_key = camera_id or camera_role or "general"
        camera_state = self._camera_alarm_state[camera_key]
        camera_state["last_alarm_at"] = now_ms
        camera_state["unknown_streak"] = 0
        camera_state["suppress_alarm_until"] = now_ms + 2_000

        alarm_record = {
            "reason": reason,
            "cameraRole": camera_role,
            "cameraId": camera_id,
            "cameraName": camera_name,
            "timestamp": iso_now(),
            "faces": faces,
            "snapshot": snapshot,
        }
        self.store.enqueue_sync_event("alarm.triggered", alarm_record)
        logger.warning("Alarm triggered: %s", alarm_record)
        self._play_alarm_sound()

    def _update_camera_alarm_state(
        self,
        camera_key: str,
        known_faces: list[dict[str, Any]],
        unknown_faces: list[dict[str, Any]],
    ) -> None:
        camera_state = self._camera_alarm_state[camera_key]
        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0
        if known_faces:
            camera_state["unknown_streak"] = 0
            camera_state["last_known_at"] = now_ms
            camera_state["last_unknown_signature"] = None
            camera_state["last_unknown_at"] = 0.0
            return
        if unknown_faces:
            camera_state["unknown_streak"] = int(camera_state["unknown_streak"]) + 1
            best_unknown = max(unknown_faces, key=lambda face: float(face.get("confidence") or 0.0))
            camera_state["last_unknown_signature"] = self._face_signature(best_unknown)
            camera_state["last_unknown_at"] = now_ms
            camera_state["last_unknown_confidence"] = float(best_unknown.get("confidence") or 0.0)
            if int(camera_state["unknown_streak"]) == 1:
                camera_state["suppress_alarm_until"] = now_ms + 1_500

    def _should_alarm_camera(self, camera_key: str, unknown_faces: list[dict[str, Any]]) -> bool:
        if not unknown_faces:
            return False

        camera_state = self._camera_alarm_state[camera_key]
        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0
        if now_ms < float(camera_state.get("suppress_alarm_until") or 0.0):
            return False
        if now_ms - float(camera_state["last_known_at"]) < self.known_grace_ms:
            return False
        best_unknown = max(unknown_faces, key=lambda face: float(face.get("confidence") or 0.0))
        best_confidence = float(best_unknown.get("confidence") or 0.0)
        if best_confidence >= self.alarm_immediate_unknown_confidence:
            return now_ms - float(camera_state["last_alarm_at"]) >= self.alarm_cooldown_ms
        if int(camera_state["unknown_streak"]) < self.alarm_unknown_frames:
            return False
        current_signature = self._face_signature(best_unknown)
        last_signature = str(camera_state.get("last_unknown_signature") or "")
        if last_signature and current_signature != last_signature:
            return False
        if now_ms - float(camera_state["last_alarm_at"]) < self.alarm_cooldown_ms:
            return False
        return True

    def _stabilize_camera_faces(
        self,
        faces: list[dict[str, Any]],
        camera_role: str,
        camera_id: str | None,
    ) -> list[dict[str, Any]]:
        if not faces:
            return faces

        camera_key = camera_id or camera_role or "general"
        camera_state = self._camera_identity_state[camera_key]
        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0

        known_faces = [face for face in faces if face["match"] and face["match"].get("label")]
        if known_faces:
            best = max(known_faces, key=lambda face: float(face["match"]["confidence"]))
            camera_state["last_known_label"] = str(best["match"]["label"])
            camera_state["last_known_confidence"] = float(best["match"]["confidence"])
            camera_state["last_known_at"] = now_ms
            return faces

        recent_label = camera_state.get("last_known_label")
        recent_seen_at = float(camera_state.get("last_known_at") or 0.0)
        recent_confidence = float(camera_state.get("last_known_confidence") or 0.0)
        if (
            recent_label
            and now_ms - recent_seen_at <= self.recognition_grace_ms
            and len(faces) == 1
        ):
            face = dict(faces[0])
            current_match = face.get("match") or {}
            if not current_match.get("label"):
                face["match"] = {
                    "label": recent_label,
                    "score": recent_confidence,
                    "confidence": recent_confidence,
                    "sampleCount": current_match.get("sampleCount", 0),
                    "stabilized": True,
                }
                return [face]

        return faces

    def _face_signature(self, face: dict[str, Any]) -> str:
        box = face.get("box") or {}
        confidence = float(face.get("confidence") or 0.0)
        return ":".join(
            [
                str(round(float(box.get("x") or 0.0) / 20.0) * 20),
                str(round(float(box.get("y") or 0.0) / 20.0) * 20),
                str(round(float(box.get("width") or 0.0) / 20.0) * 20),
                str(round(float(box.get("height") or 0.0) / 20.0) * 20),
                str(round(confidence * 10)),
            ],
        )

    def _play_alarm_sound(self) -> None:
        sound = self.alarm_sound_path
        if not sound.exists():
            logger.warning("Alarm sound file not found: %s", sound)
            return

        try:
            if platform.system() == "Windows":
                import winsound

                winsound.PlaySound(str(sound), winsound.SND_FILENAME | winsound.SND_ASYNC)
                return

            if shutil.which("afplay"):
                subprocess.Popen(["afplay", str(sound)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return

            if shutil.which("paplay"):
                subprocess.Popen(["paplay", str(sound)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return

            if shutil.which("ffplay"):
                subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(sound)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return

            if shutil.which("aplay"):
                subprocess.Popen(["aplay", str(sound)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return

            logger.warning("No system audio player found for alarm playback")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to play alarm sound: %s", exc)

    def _sync_loop(self) -> None:
        while not self._sync_stop.is_set():
            try:
                self._flush_sync_queue()
            except Exception:
                pass
            self._sync_stop.wait(self.sync_interval_ms / 1000.0)

    def _flush_sync_queue(self) -> dict[str, Any]:
        if not self.sync_endpoint_url:
            return {"ok": False, "reason": "sync endpoint not configured", "pending": len(self.store.list_sync_events(1000))}

        with self._sync_lock:
            events = self.store.list_sync_events(100)
            if not events:
                return {"ok": True, "synced": 0, "pending": 0}

            payload = {
                "agentId": os.getenv("AGENT_ID", "local-agent"),
                "events": [
                    {
                        "id": row["id"],
                        "type": row["event_type"],
                        "payload": json.loads(row["payload"]),
                        "createdAt": row["created_at"],
                        "retryCount": row["retry_count"],
                    }
                    for row in events
                ],
            }
            data = json.dumps(payload).encode("utf-8")
            request = urllib_request.Request(
                self.sync_endpoint_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib_request.urlopen(request, timeout=10) as response:
                    response_body = response.read().decode("utf-8")
                    if response.status >= 200 and response.status < 300:
                        self.store.mark_sync_events_synced([event["id"] for event in events])
                        return {"ok": True, "synced": len(events), "response": response_body}
                    raise RuntimeError(f"Sync failed with HTTP {response.status}")
            except urllib_error.URLError as exc:
                for event in events:
                    self.store.mark_sync_event_failed(int(event["id"]), str(exc))
                return {"ok": False, "error": str(exc), "pending": len(self.store.list_sync_events(1000))}


class RegisterRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    imageBase64: str
    cameraRole: str | None = None
    cameraId: str | None = None
    tenantId: str | None = None


class EmployeePhotosRequest(BaseModel):
    photos: list[str] = Field(default_factory=list)
    tenantId: str | None = None


class RecognizeRequest(BaseModel):
    imageBase64: str
    cameraRole: str | None = None
    cameraId: str | None = None
    tenantId: str | None = None


class BootstrapRequest(BaseModel):
    tenantName: str
    adminEmail: str
    adminPassword: str
    plan: str = "local"
    licenseKey: str | None = None
    cloudSyncEnabled: bool = False


class LoginRequest(BaseModel):
    tenantId: str
    email: str
    password: str


engine = FaceEngine()
app = FastAPI(title="Python Face Recognizer", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return engine.health()


ROOT_DIR = Path(__file__).resolve().parents[1]


@app.get("/")
async def root() -> Response:
    return Response(status_code=307, headers={"Location": "/live"})


@app.get("/live")
async def live_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "index.html", media_type="text/html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "admin.html", media_type="text/html")


@app.get("/setup")
async def setup_page() -> FileResponse:
    return FileResponse(ROOT_DIR / "setup.html", media_type="text/html")


@app.get("/app.js")
async def app_js() -> FileResponse:
    return FileResponse(ROOT_DIR / "public" / "app.js", media_type="application/javascript")


@app.get("/setup.js")
async def setup_js() -> FileResponse:
    return FileResponse(ROOT_DIR / "public" / "setup.js", media_type="application/javascript")


@app.post("/start")
async def start(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = payload or {}
    return engine.start(
        str(data.get("cameraId") or "").strip() or None,
        str(data.get("cameraRole") or "").strip() or None,
    )


@app.post("/stop")
async def stop() -> dict[str, Any]:
    return engine.stop()


@app.get("/status")
async def status() -> dict[str, Any]:
    return engine.status()


@app.on_event("startup")
async def startup_event() -> None:
    if engine.auto_start_detection:
        try:
            engine.start()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Startup auto-start failed: %s", exc)


@app.get("/alarm.wav")
async def alarm_sound() -> Response:
    sound_path = engine.alarm_sound()
    if sound_path is None:
        raise HTTPException(status_code=404, detail="Alarm sound not configured")
    return FileResponse(sound_path, media_type="audio/wav", filename=sound_path.name)


@app.get("/snapshots/{filename:path}")
async def snapshot_file(filename: str) -> Response:
    root = engine.snapshot_path.resolve()
    path = (root / filename).resolve()
    if root not in path.parents and path != root:
        raise HTTPException(status_code=400, detail="Invalid snapshot path")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return FileResponse(path, media_type="image/jpeg", filename=path.name)


@app.get("/cameras")
async def cameras(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"cameras": engine.list_cameras(x_tenant_id)}


@app.get("/departments")
async def departments(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"departments": engine.list_departments(x_tenant_id)}


@app.post("/departments")
async def upsert_department(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"department": engine.upsert_department(payload, x_tenant_id)}


@app.put("/departments/{department_id}")
async def update_department(department_id: str, payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    payload["id"] = department_id
    return {"department": engine.upsert_department(payload, x_tenant_id)}


@app.delete("/departments/{department_id}")
async def delete_department(department_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"ok": True, "removed": engine.delete_department(department_id, x_tenant_id)}


@app.get("/employees")
async def employees(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"employees": engine.list_employees(x_tenant_id)}


@app.post("/employees")
async def upsert_employee(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"employee": engine.upsert_employee(payload, x_tenant_id)}


@app.put("/employees/{employee_id}")
async def update_employee(employee_id: str, payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    payload["id"] = employee_id
    return {"employee": engine.upsert_employee(payload, x_tenant_id)}


@app.delete("/employees/{employee_id}")
async def delete_employee(employee_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"ok": True, "removed": engine.delete_employee(employee_id, x_tenant_id)}


@app.post("/employees/cleanup-orphan-faces")
async def cleanup_orphan_employee_faces(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return engine.cleanup_orphan_faces(x_tenant_id)


@app.post("/employees/{employee_id}/photos")
async def upload_employee_photos(employee_id: str, payload: EmployeePhotosRequest, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    images = [decode_base64_image(photo) for photo in payload.photos]
    return await asyncio.to_thread(engine.register_employee_photos, employee_id, images, payload.tenantId or x_tenant_id)


@app.post("/cameras")
async def add_camera(payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    camera = engine.upsert_camera(payload, x_tenant_id)
    if engine.auto_start_detection:
        engine.start()
    return {"camera": camera}


@app.get("/cameras/{camera_id}")
async def get_camera(camera_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    camera = engine.get_camera(camera_id, x_tenant_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"camera": camera}


@app.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, payload: dict[str, Any], x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    payload["id"] = camera_id
    camera = engine.upsert_camera(payload, x_tenant_id)
    if engine.auto_start_detection:
        engine.start()
    return {"camera": camera}


@app.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    removed = engine.delete_camera(camera_id, x_tenant_id)
    if engine.auto_start_detection:
        engine.start()
    return {"ok": True, "removed": removed}


@app.post("/recognize")
async def recognize(payload: RecognizeRequest, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    image = decode_base64_image(payload.imageBase64)
    result = await asyncio.to_thread(
        engine.recognize,
        image,
        payload.cameraRole or "general",
        payload.cameraId,
        payload.tenantId or x_tenant_id,
    )
    return result


@app.post("/register")
async def register(payload: RegisterRequest, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    image: np.ndarray | None = None
    try:
        image = decode_base64_image(payload.imageBase64)
    except HTTPException:
        image = None
    if image is None and (payload.cameraId or payload.cameraRole):
        fallback = await asyncio.to_thread(engine.latest_frame_image, payload.cameraId, payload.cameraRole)
        if fallback is not None:
            image = fallback
    if image is None:
        fallback = await asyncio.to_thread(engine.latest_detectable_frame)
        if fallback is not None:
            image = fallback
    if image is None:
        raise HTTPException(status_code=400, detail="No face found in the current frame.")
    result = await asyncio.to_thread(
        engine.register,
        payload.label.strip(),
        image,
        payload.cameraRole or "general",
        payload.cameraId,
        payload.tenantId or x_tenant_id,
    )
    return result


@app.post("/faces/register")
async def register_face(payload: RegisterRequest, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return await register(payload, x_tenant_id)


@app.get("/faces")
async def faces(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"faces": await asyncio.to_thread(engine.list_faces, x_tenant_id)}


@app.delete("/faces/{label}")
async def delete_face(label: str, x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    trimmed = label.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Label is required")
    removed = await asyncio.to_thread(engine.remove_face, trimmed, x_tenant_id)
    return {"ok": True, "removed": removed}


@app.post("/faces/clear")
async def clear_faces(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    await asyncio.to_thread(engine.clear_faces, x_tenant_id)
    return {"ok": True}


@app.get("/attendance")
async def attendance(x_tenant_id: str | None = Header(default=None)) -> dict[str, Any]:
    return {"attendance": await asyncio.to_thread(engine.list_attendance, x_tenant_id)}


@app.get("/alarms")
async def alarms(limit: int = 100) -> dict[str, Any]:
    return {"alarms": await asyncio.to_thread(engine.store.list_alarm_events, limit)}


@app.delete("/alarms")
@app.post("/alarms/clear")
async def clear_alarms() -> dict[str, Any]:
    await asyncio.to_thread(engine.store.clear_sync_events)
    return {"ok": True}


@app.get("/sync/status")
async def sync_status() -> dict[str, Any]:
    return engine.sync_status()


@app.get("/sync/pending")
async def sync_pending() -> dict[str, Any]:
    return {"events": await asyncio.to_thread(engine.store.list_sync_events)}


@app.post("/sync/run")
async def sync_run() -> dict[str, Any]:
    return await asyncio.to_thread(engine.sync_now)


@app.get("/attendance.csv")
async def attendance_csv(x_tenant_id: str | None = Header(default=None)) -> Response:
    rows = await asyncio.to_thread(engine.list_attendance, x_tenant_id)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "label",
        "firstAppearance",
        "lastAppearance",
        "checkInRole",
        "checkOutRole",
        "firstCameraId",
        "lastCameraId",
        "firstCameraName",
        "lastCameraName",
        "firstDepartmentId",
        "lastDepartmentId",
        "firstDepartmentName",
        "lastDepartmentName",
        "firstSnapshotPath",
        "lastSnapshotPath",
        "lastConfidence",
        "maxConfidence",
        "appearances",
    ])
    for row in rows:
        writer.writerow([
            row["label"],
            row["first_appearance"],
            row["last_appearance"],
            row.get("first_camera_role"),
            row.get("last_camera_role"),
            row.get("first_camera_id"),
            row.get("last_camera_id"),
            row.get("first_camera_name"),
            row.get("last_camera_name"),
            row.get("first_department_id"),
            row.get("last_department_id"),
            row.get("first_department_name"),
            row.get("last_department_name"),
            row.get("first_snapshot_path"),
            row.get("last_snapshot_path"),
            row.get("last_confidence"),
            row.get("max_confidence"),
            row.get("appearances"),
        ])
    return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8")


@app.get("/stream.mjpg")
async def stream_mjpg(
    cameraId: str | None = None,
    cameraRole: str | None = None,
    x_tenant_id: str | None = Header(default=None),
) -> Response:
    camera = engine.stream_camera(cameraId, cameraRole)
    if camera is None:
        raise HTTPException(status_code=404, detail="No enabled camera found")

    boundary = b"--frame\r\n"
    headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate, proxy-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
        "Connection": "keep-alive",
    }

    async def frame_iterator() -> Any:
        camera_id = str(camera["id"])
        last_sent_at = 0.0
        try:
            while True:
                with engine._camera_frames_lock:
                    frame_state = dict(engine._camera_frames.get(camera_id, {}))
                frame_bytes = frame_state.get("latest_frame")
                latest_at = float(frame_state.get("latest_at") or 0.0)
                if not frame_bytes or latest_at <= last_sent_at:
                    await asyncio.sleep(0.04)
                    continue
                last_sent_at = latest_at
                yield boundary
                yield b"Content-Type: image/jpeg\r\n"
                yield f"Content-Length: {len(frame_bytes)}\r\n\r\n".encode("utf-8")
                yield frame_bytes
                yield b"\r\n"
        except asyncio.CancelledError:
            return

    return StreamingResponse(frame_iterator(), media_type="multipart/x-mixed-replace; boundary=frame", headers=headers)


@app.get("/frame.jpg")
async def frame_jpg(
    cameraId: str | None = None,
    cameraRole: str | None = None,
    x_tenant_id: str | None = Header(default=None),
) -> Response:
    camera = engine.stream_camera(cameraId, cameraRole)
    if camera is None:
        raise HTTPException(status_code=404, detail="No enabled camera found")
    with engine._camera_frames_lock:
        frame_state = dict(engine._camera_frames.get(str(camera["id"]), {}))
    frame_bytes = frame_state.get("latest_frame")
    if not frame_bytes:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})
    return Response(
        content=frame_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.websocket("/ws/live")
async def live_socket(websocket: WebSocket) -> None:
    await websocket.accept()
    last_sent: dict[str, float] = {}
    try:
        while True:
            status_payload = engine.status()
            frames: list[dict[str, Any]] = []
            with engine._camera_frames_lock:
                frame_states = {
                    camera_id: {
                        "latest_frame": state.get("latest_frame"),
                        "latest_at": float(state.get("latest_at") or 0.0),
                    }
                    for camera_id, state in engine._camera_frames.items()
                }
            for camera in status_payload.get("cameras", []):
                camera_id = str(camera.get("id") or "")
                state = frame_states.get(camera_id) or {}
                latest_at = float(state.get("latest_at") or 0.0)
                frame_bytes = state.get("latest_frame")
                if not frame_bytes or latest_at <= float(last_sent.get(camera_id) or 0.0):
                    continue
                last_sent[camera_id] = latest_at
                frames.append(
                    {
                        "cameraId": camera_id,
                        "timestamp": datetime.fromtimestamp(latest_at, tz=timezone.utc).isoformat(timespec="milliseconds"),
                        "jpegBase64": base64.b64encode(frame_bytes).decode("ascii"),
                    }
                )
            await websocket.send_json(
                {
                    "type": "live",
                    "status": status_payload,
                    "frames": frames,
                }
            )
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
    except asyncio.CancelledError:
        return


@app.post("/tenant/bootstrap")
async def bootstrap(payload: BootstrapRequest) -> dict[str, Any]:
    tenant = await asyncio.to_thread(engine.store.ensure_tenant, payload.tenantName)
    user = await asyncio.to_thread(engine.store.create_user, tenant["id"], payload.adminEmail, payload.adminPassword, "admin")
    license_row = None
    if payload.licenseKey:
        license_row = await asyncio.to_thread(
            engine.store.upsert_license,
            tenant["id"],
            payload.licenseKey,
            payload.plan,
            payload.cloudSyncEnabled,
            None,
        )
    return {"tenant": tenant, "user": user, "license": license_row}


@app.post("/auth/login")
async def login(payload: LoginRequest) -> dict[str, Any]:
    user = await asyncio.to_thread(engine.store.authenticate_user, payload.tenantId, payload.email, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    license_row = await asyncio.to_thread(engine.store.get_license, payload.tenantId)
    return {
        "ok": True,
        "tenantId": normalize_tenant_id(payload.tenantId),
        "user": user,
        "license": license_row,
    }
