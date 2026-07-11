from __future__ import annotations

import asyncio
import base64
import csv
import json
import math
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from io import StringIO
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from insightface.app import FaceAnalysis


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="milliseconds")


def parse_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def decode_base64_image(image_base64: str) -> np.ndarray:
    try:
        payload = base64.b64decode(image_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid base64 image payload") from exc

    data = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Unable to decode image")
    return image


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        return vector
    return vector / norm


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


class SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._ensure_schema()

    def connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS cameras (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    camera_role TEXT NOT NULL DEFAULT 'general',
                    rtsp_url TEXT NOT NULL,
                    rtsp_username TEXT,
                    rtsp_password TEXT,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS known_faces (
                    label TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS face_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    label TEXT NOT NULL,
                    embedding TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(label) REFERENCES known_faces(label) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS attendance_records (
                    label TEXT PRIMARY KEY,
                    first_appearance TEXT NOT NULL,
                    last_appearance TEXT NOT NULL,
                    first_camera_role TEXT NOT NULL DEFAULT 'general',
                    last_camera_role TEXT NOT NULL DEFAULT 'general',
                    appearances INTEGER NOT NULL DEFAULT 0,
                    max_confidence REAL NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS sync_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    synced_at TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                );
                """
            )
            self._ensure_column(conn, "cameras", "camera_role", "TEXT NOT NULL DEFAULT 'general'")
            self._ensure_column(conn, "attendance_records", "first_camera_role", "TEXT NOT NULL DEFAULT 'general'")
            self._ensure_column(conn, "attendance_records", "last_camera_role", "TEXT NOT NULL DEFAULT 'general'")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def list_cameras(self) -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, camera_role, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras
                ORDER BY created_at ASC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_camera(self, camera_id: str) -> dict[str, Any] | None:
        with self._lock, self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, name, camera_role, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras
                WHERE id = ?
                """,
                (camera_id,),
            ).fetchone()
            return dict(row) if row else None

    def upsert_camera(self, camera: dict[str, Any]) -> dict[str, Any]:
        camera_id = str(camera.get("id") or "").strip() or self._generate_id()
        name = str(camera.get("name") or camera_id).strip()
        camera_role = str(camera.get("cameraRole") or camera.get("camera_role") or "general").strip().lower()
        if camera_role not in {"general", "check_in", "check_out"}:
            camera_role = "general"
        rtsp_url = str(camera.get("rtspUrl") or camera.get("rtsp_url") or "").strip()
        if not rtsp_url:
            raise HTTPException(status_code=400, detail="rtspUrl is required")
        rtsp_username = self._clean_optional(camera.get("rtspUsername") or camera.get("rtsp_username"))
        rtsp_password = self._clean_optional(camera.get("rtspPassword") or camera.get("rtsp_password"))
        enabled = 1 if bool(camera.get("enabled", True)) else 0
        now = iso_now()

        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO cameras (id, name, camera_role, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    camera_role = excluded.camera_role,
                    rtsp_url = excluded.rtsp_url,
                    rtsp_username = excluded.rtsp_username,
                    rtsp_password = excluded.rtsp_password,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (camera_id, name, camera_role, rtsp_url, rtsp_username, rtsp_password, enabled, now, now),
            )
            row = conn.execute(
                """
                SELECT id, name, camera_role, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras
                WHERE id = ?
                """,
                (camera_id,),
            ).fetchone()
            if row is None:
                return {
                    "id": camera_id,
                    "name": name,
                    "camera_role": camera_role,
                    "rtsp_url": rtsp_url,
                    "rtsp_username": rtsp_username,
                    "rtsp_password": rtsp_password,
                    "enabled": enabled,
                    "created_at": now,
                    "updated_at": now,
                }
            return dict(row)

    def delete_camera(self, camera_id: str) -> bool:
        with self._lock, self.connection() as conn:
            deleted = conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,)).rowcount
            return deleted > 0

    def get_default_camera(self) -> dict[str, Any] | None:
        with self._lock, self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, name, camera_role, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras
                WHERE enabled = 1
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None

    def clear_faces(self) -> None:
        with self._lock, self.connection() as conn:
            conn.execute("DELETE FROM face_embeddings")
            conn.execute("DELETE FROM known_faces")

    def remove_face(self, label: str) -> bool:
        with self._lock, self.connection() as conn:
            deleted = conn.execute("DELETE FROM known_faces WHERE label = ?", (label,)).rowcount
            return deleted > 0

    def list_faces(self) -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT f.label, f.updated_at, COUNT(e.id) AS sampleCount
                FROM known_faces f
                LEFT JOIN face_embeddings e ON e.label = f.label
                GROUP BY f.label, f.updated_at
                ORDER BY f.label COLLATE NOCASE
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def register_face(self, label: str, embedding: np.ndarray) -> dict[str, Any]:
        label = label.strip()
        if not label:
            raise HTTPException(status_code=400, detail="Label is required")
        normalized = normalize_embedding(embedding).astype(np.float32).tolist()
        now = iso_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO known_faces (label, updated_at)
                VALUES (?, ?)
                ON CONFLICT(label) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (label, now),
            )
            conn.execute(
                """
                INSERT INTO face_embeddings (label, embedding, created_at)
                VALUES (?, ?, ?)
                """,
                (label, json.dumps(normalized), now),
            )
            row = conn.execute(
                """
                SELECT f.label, f.updated_at, COUNT(e.id) AS sampleCount
                FROM known_faces f
                LEFT JOIN face_embeddings e ON e.label = f.label
                WHERE f.label = ?
                GROUP BY f.label, f.updated_at
                """,
                (label,),
            ).fetchone()
            if row is None:
                return {
                    "label": label,
                    "updatedAt": now,
                    "sampleCount": 1,
                }
            return dict(row)

    def all_embeddings(self) -> list[tuple[str, np.ndarray, str, int]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT f.label, e.embedding, f.updated_at
                FROM known_faces f
                JOIN face_embeddings e ON e.label = f.label
                ORDER BY f.label COLLATE NOCASE, e.id ASC
                """
            ).fetchall()
            grouped: dict[str, tuple[list[np.ndarray], str]] = {}
            for row in rows:
                label = str(row["label"])
                embedding = np.asarray(json.loads(row["embedding"]), dtype=np.float32)
                updated_at = str(row["updated_at"])
                if label not in grouped:
                    grouped[label] = ([], updated_at)
                grouped[label][0].append(embedding)
            result: list[tuple[str, np.ndarray, str, int]] = []
            for label, (embeddings, updated_at) in grouped.items():
                for index, embedding in enumerate(embeddings):
                    result.append((label, embedding, updated_at, len(embeddings)))
            return result

    def record_attendance(
        self,
        label: str,
        confidence: float,
        timestamp: str,
        cooldown_ms: int,
        camera_role: str = "general",
    ) -> dict[str, Any]:
        role = camera_role if camera_role in {"general", "check_in", "check_out"} else "general"
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM attendance_records WHERE label = ?",
                (label,),
            ).fetchone()
            if row is None:
                record = {
                    "label": label,
                    "first_appearance": timestamp,
                    "last_appearance": timestamp,
                    "first_camera_role": role,
                    "last_camera_role": role,
                    "appearances": 1,
                    "max_confidence": float(confidence),
                }
            else:
                previous_last = datetime.fromisoformat(str(row["last_appearance"]))
                current = datetime.fromisoformat(timestamp)
                appearances = int(row["appearances"])
                if (current - previous_last).total_seconds() * 1000.0 >= cooldown_ms:
                    appearances += 1
                first_role = str(row["first_camera_role"] or "general")
                record = {
                    "label": label,
                    "first_appearance": str(row["first_appearance"]),
                    "last_appearance": timestamp,
                    "first_camera_role": first_role,
                    "last_camera_role": role,
                    "appearances": appearances,
                    "max_confidence": max(float(row["max_confidence"]), float(confidence)),
                }
            conn.execute(
                """
                INSERT INTO attendance_records (label, first_appearance, last_appearance, first_camera_role, last_camera_role, appearances, max_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(label) DO UPDATE SET
                    first_appearance = excluded.first_appearance,
                    last_appearance = excluded.last_appearance,
                    first_camera_role = excluded.first_camera_role,
                    last_camera_role = excluded.last_camera_role,
                    appearances = excluded.appearances,
                    max_confidence = excluded.max_confidence
                """,
                (
                    record["label"],
                    record["first_appearance"],
                    record["last_appearance"],
                    record["first_camera_role"],
                    record["last_camera_role"],
                    record["appearances"],
                    record["max_confidence"],
                ),
            )
            return record

    def list_attendance(self) -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT label, first_appearance, last_appearance, first_camera_role, last_camera_role, appearances, max_confidence
                FROM attendance_records
                ORDER BY label COLLATE NOCASE
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def enqueue_sync_event(self, event_type: str, payload: dict[str, Any]) -> int:
        with self._lock, self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO sync_events (event_type, payload, created_at)
                VALUES (?, ?, ?)
                """,
                (event_type, json.dumps(payload), iso_now()),
            )
            return int(row.lastrowid)

    def list_sync_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, event_type, payload, created_at, synced_at, retry_count, last_error
                FROM sync_events
                WHERE synced_at IS NULL
                ORDER BY id ASC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_sync_events_synced(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join(["?"] * len(ids))
        with self._lock, self.connection() as conn:
            conn.execute(
                f"""
                UPDATE sync_events
                SET synced_at = ?, last_error = NULL
                WHERE id IN ({placeholders})
                """,
                [iso_now(), *ids],
            )

    def mark_sync_event_failed(self, event_id: int, error_message: str) -> None:
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                UPDATE sync_events
                SET retry_count = retry_count + 1, last_error = ?
                WHERE id = ?
                """,
                (error_message[:500], event_id),
            )

    def _generate_id(self) -> str:
        return f"cam-{datetime.now(timezone.utc).timestamp():.0f}-{os.urandom(3).hex()}"

    def _clean_optional(self, value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None


class FaceEngine:
    def __init__(self) -> None:
        self.snapshot_path = Path(os.getenv("SNAPSHOT_PATH", "./snapshots"))
        db_path = Path(os.getenv("PYTHON_DB_PATH", "./data/app.db"))
        self.store = SQLiteStore(db_path)

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
        default_alarm = Path.home() / "Downloads" / "mixkit-data-scaner-2847.wav"
        configured_alarm = os.getenv("ALARM_SOUND_PATH")
        self.alarm_sound_path = Path(configured_alarm).expanduser() if configured_alarm else default_alarm
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
        if self.sync_enabled and self.sync_endpoint_url:
            self._sync_thread = threading.Thread(target=self._sync_loop, daemon=True)
            self._sync_thread.start()

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
            "faces": len(self.store.list_faces()),
            "cameras": len(self.store.list_cameras()),
            "alarmSoundAvailable": self.alarm_sound_path.exists(),
            "timestamp": iso_now(),
        }

    def alarm_sound(self) -> Path | None:
        if self.alarm_sound_path.exists():
            return self.alarm_sound_path
        return None

    def recognize(self, image: np.ndarray, camera_role: str = "general", camera_id: str | None = None) -> dict[str, Any]:
        with self._model_lock:
            faces = self._model.get(image)

        detected = [self._serialize_face(face) for face in self._filter_faces(faces)]
        snapshot = self._maybe_save_snapshot(image, detected)
        state = "faces detected" if detected else "no face detected"
        if snapshot is not None:
            state = "snapshot saved"
        for face in detected:
            if face["match"] and face["match"].get("label"):
                self.store.record_attendance(
                    str(face["match"]["label"]),
                    float(face["match"]["confidence"]),
                    iso_now(),
                    self.snapshot_cooldown_ms,
                    camera_role,
                )
                self.store.enqueue_sync_event(
                    "attendance.recorded",
                    {
                        "label": str(face["match"]["label"]),
                        "confidence": float(face["match"]["confidence"]),
                        "timestamp": iso_now(),
                        "cameraRole": camera_role,
                        "cameraId": camera_id,
                        "snapshot": snapshot,
                    },
                )
        return {
            "state": state,
            "faces": detected,
            "snapshot": snapshot,
        }

    def register(self, label: str, image: np.ndarray, camera_role: str = "general", camera_id: str | None = None) -> dict[str, Any]:
        label = label.strip()
        if not label:
            raise HTTPException(status_code=400, detail="Label is required")

        with self._model_lock:
            faces = self._filter_faces(self._model.get(image))

        if not faces:
            raise HTTPException(status_code=400, detail="No face found in the current frame.")

        face = max(faces, key=lambda item: float(item.bbox[2] - item.bbox[0]) * float(item.bbox[3] - item.bbox[1]) * float(getattr(item, "det_score", 0.0)))
        embedding = self._embedding_for(face)
        if embedding is None:
            raise HTTPException(status_code=400, detail="Face embedding could not be generated.")

        sample = self.store.register_face(label, embedding)
        self.store.enqueue_sync_event(
            "face.registered",
            {
                "label": sample.label,
                "sampleCount": sample.sample_count,
                "updatedAt": sample.updatedAt,
                "cameraRole": camera_role,
                "cameraId": camera_id,
            },
        )
        return {
            "label": sample.label,
            "sampleCount": sample.sample_count,
            "updatedAt": sample.updatedAt,
        }

    def list_faces(self) -> list[dict[str, Any]]:
        return self.store.list_faces()

    def remove_face(self, label: str) -> bool:
        return self.store.remove_face(label)

    def clear_faces(self) -> None:
        self.store.clear_faces()
        self.store.enqueue_sync_event("faces.cleared", {})

    def list_cameras(self) -> list[dict[str, Any]]:
        return self.store.list_cameras()

    def get_camera(self, camera_id: str) -> dict[str, Any] | None:
        return self.store.get_camera(camera_id)

    def upsert_camera(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.store.upsert_camera(payload)

    def delete_camera(self, camera_id: str) -> bool:
        return self.store.delete_camera(camera_id)

    def default_camera(self) -> dict[str, Any] | None:
        return self.store.get_default_camera()

    def list_attendance(self) -> list[dict[str, Any]]:
        return self.store.list_attendance()

    def sync_status(self) -> dict[str, Any]:
        return {
            "enabled": self.sync_enabled,
            "endpointUrl": self.sync_endpoint_url or None,
            "pending": len(self.store.list_sync_events(1_000)),
            "running": bool(self._sync_thread and self._sync_thread.is_alive()),
        }

    def sync_now(self) -> dict[str, Any]:
        return self._flush_sync_queue()

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

    def _serialize_face(self, face: Any) -> dict[str, Any]:
        embedding = self._embedding_for(face)
        assert embedding is not None
        match = self._match_embedding(embedding)
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
        }

    def _match_embedding(self, embedding: np.ndarray) -> dict[str, Any] | None:
        best: dict[str, Any] | None = None
        groups: dict[str, list[np.ndarray]] = {}
        for label, sample_embedding, _updated_at, _sample_count in self.store.all_embeddings():
            groups.setdefault(label, []).append(sample_embedding)

        for label, samples in groups.items():
            scores = [cosine_similarity(embedding, sample) for sample in samples]
            if not scores:
                continue
            scores.sort(reverse=True)
            top_scores = scores[:3]
            score = max(top_scores[0], sum(top_scores) / len(top_scores))
            if best is None or score > float(best["score"]):
                best = {
                    "label": label,
                    "score": score,
                    "confidence": score,
                    "sampleCount": len(samples),
                }

        if best is None or float(best["score"]) < self.match_threshold:
            return None
        return best

    def _maybe_save_snapshot(self, image: np.ndarray, faces: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not faces:
            return None

        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0
        with self._snapshot_lock:
            if now_ms - self._last_snapshot_at < self.snapshot_cooldown_ms:
                return None

        best_face = max(faces, key=lambda face: float(face["confidence"]))
        timestamp = iso_now().replace(":", "-").replace("+", "-")
        filename = f"face-{timestamp}.jpg"
        path = self.snapshot_path / filename
        self.snapshot_path.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(str(path), image)
        if not ok:
            return None
        with self._snapshot_lock:
            self._last_snapshot_at = now_ms
        return {
            "path": str(path),
            "timestamp": iso_now(),
            "confidence": float(best_face["confidence"]),
        }

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


class RecognizeRequest(BaseModel):
    imageBase64: str
    cameraRole: str | None = None
    cameraId: str | None = None


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


@app.get("/alarm.wav")
async def alarm_sound() -> Response:
    sound_path = engine.alarm_sound()
    if sound_path is None:
        raise HTTPException(status_code=404, detail="Alarm sound not configured")
    return FileResponse(sound_path, media_type="audio/wav", filename=sound_path.name)


@app.get("/cameras")
async def cameras() -> dict[str, Any]:
    return {"cameras": engine.list_cameras()}


@app.post("/cameras")
async def add_camera(payload: dict[str, Any]) -> dict[str, Any]:
    return {"camera": engine.upsert_camera(payload)}


@app.get("/cameras/{camera_id}")
async def get_camera(camera_id: str) -> dict[str, Any]:
    camera = engine.get_camera(camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    return {"camera": camera}


@app.put("/cameras/{camera_id}")
async def update_camera(camera_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload["id"] = camera_id
    return {"camera": engine.upsert_camera(payload)}


@app.delete("/cameras/{camera_id}")
async def delete_camera(camera_id: str) -> dict[str, Any]:
    removed = engine.delete_camera(camera_id)
    return {"ok": True, "removed": removed}


@app.post("/recognize")
async def recognize(payload: RecognizeRequest) -> dict[str, Any]:
    image = decode_base64_image(payload.imageBase64)
    result = await asyncio.to_thread(
        engine.recognize,
        image,
        payload.cameraRole or "general",
        payload.cameraId,
    )
    return result


@app.post("/register")
async def register(payload: RegisterRequest) -> dict[str, Any]:
    image = decode_base64_image(payload.imageBase64)
    result = await asyncio.to_thread(
        engine.register,
        payload.label.strip(),
        image,
        payload.cameraRole or "general",
        payload.cameraId,
    )
    return result


@app.get("/faces")
async def faces() -> dict[str, Any]:
    return {"faces": await asyncio.to_thread(engine.list_faces)}


@app.delete("/faces/{label}")
async def delete_face(label: str) -> dict[str, Any]:
    trimmed = label.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Label is required")
    removed = await asyncio.to_thread(engine.remove_face, trimmed)
    return {"ok": True, "removed": removed}


@app.post("/faces/clear")
async def clear_faces() -> dict[str, Any]:
    await asyncio.to_thread(engine.clear_faces)
    return {"ok": True}


@app.get("/attendance")
async def attendance() -> dict[str, Any]:
    return {"attendance": await asyncio.to_thread(engine.list_attendance)}


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
async def attendance_csv() -> Response:
    rows = await asyncio.to_thread(engine.list_attendance)
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["label", "firstAppearance", "lastAppearance", "appearances", "maxConfidence"])
    for row in rows:
        writer.writerow([
            row["label"],
            row["first_appearance"],
            row["last_appearance"],
            row["appearances"],
            row["max_confidence"],
        ])
    return Response(content=buffer.getvalue(), media_type="text/csv; charset=utf-8")
