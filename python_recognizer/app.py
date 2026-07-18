from __future__ import annotations

import asyncio
import base64
import hashlib
import csv
import json
import math
import os
import platform
import secrets
import shutil
import subprocess
import logging
import sqlite3
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


logger = logging.getLogger("python_recognizer")
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)


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


def scope_key(tenant_id: str, value: str) -> str:
    tenant = normalize_tenant_id(tenant_id)
    text = str(value or "").strip()
    if not text:
        return text
    if text.startswith(f"{tenant}::"):
        return text
    if "::" in text:
        return text
    return f"{tenant}::{text}"


def normalize_tenant_id(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "default"
    cleaned = [char if char.isalnum() or char in {"-", "_"} else "-" for char in text]
    return "".join(cleaned)[:80] or "default"


def unscope_key(value: str, tenant_id: str) -> str:
    tenant = normalize_tenant_id(tenant_id)
    prefix = f"{tenant}::"
    if value.startswith(prefix):
        return value[len(prefix) :]
    if tenant == "default" and "::" not in value:
        return value
    return value


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
                    department_id TEXT,
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
                    employee_id TEXT,
                    embedding TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(label) REFERENCES known_faces(label) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS departments (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, name)
                );
                CREATE TABLE IF NOT EXISTS employees (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL DEFAULT 'default',
                    name TEXT NOT NULL,
                    employee_code TEXT,
                    role TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS employee_departments (
                    employee_id TEXT NOT NULL,
                    department_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(employee_id, department_id)
                );
                CREATE TABLE IF NOT EXISTS attendance_records (
                    label TEXT PRIMARY KEY,
                    first_appearance TEXT NOT NULL,
                    last_appearance TEXT NOT NULL,
                    first_camera_role TEXT NOT NULL DEFAULT 'general',
                    last_camera_role TEXT NOT NULL DEFAULT 'general',
                    first_camera_id TEXT,
                    last_camera_id TEXT,
                    first_camera_name TEXT,
                    last_camera_name TEXT,
                    first_department_id TEXT,
                    last_department_id TEXT,
                    first_department_name TEXT,
                    last_department_name TEXT,
                    first_snapshot_path TEXT,
                    last_snapshot_path TEXT,
                    last_confidence REAL NOT NULL DEFAULT 0,
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
                CREATE TABLE IF NOT EXISTS tenants (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    email TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'admin',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, email)
                );
                CREATE TABLE IF NOT EXISTS licenses (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    license_key TEXT NOT NULL,
                    plan TEXT NOT NULL DEFAULT 'local',
                    status TEXT NOT NULL DEFAULT 'active',
                    cloud_sync_enabled INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    activated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(tenant_id, license_key)
                );
                """
            )
            self._ensure_column(conn, "cameras", "camera_role", "TEXT NOT NULL DEFAULT 'general'")
            self._ensure_column(conn, "cameras", "department_id", "TEXT")
            self._ensure_column(conn, "face_embeddings", "employee_id", "TEXT")
            self._ensure_column(conn, "attendance_records", "first_camera_role", "TEXT NOT NULL DEFAULT 'general'")
            self._ensure_column(conn, "attendance_records", "last_camera_role", "TEXT NOT NULL DEFAULT 'general'")
            self._ensure_column(conn, "attendance_records", "first_camera_id", "TEXT")
            self._ensure_column(conn, "attendance_records", "last_camera_id", "TEXT")
            self._ensure_column(conn, "attendance_records", "first_camera_name", "TEXT")
            self._ensure_column(conn, "attendance_records", "last_camera_name", "TEXT")
            self._ensure_column(conn, "attendance_records", "first_department_id", "TEXT")
            self._ensure_column(conn, "attendance_records", "last_department_id", "TEXT")
            self._ensure_column(conn, "attendance_records", "first_department_name", "TEXT")
            self._ensure_column(conn, "attendance_records", "last_department_name", "TEXT")
            self._ensure_column(conn, "attendance_records", "first_snapshot_path", "TEXT")
            self._ensure_column(conn, "attendance_records", "last_snapshot_path", "TEXT")
            self._ensure_column(conn, "attendance_records", "last_confidence", "REAL NOT NULL DEFAULT 0")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def list_cameras(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, camera_role, department_id, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras
                ORDER BY created_at ASC
                """
            ).fetchall()
            scoped = scope_key(tenant_id, "")
            legacy_default = normalize_tenant_id(tenant_id) == "default"
            results = []
            for row in rows:
                camera_id = str(row["id"])
                if camera_id.startswith(scoped) or (legacy_default and "::" not in camera_id):
                    payload = dict(row)
                    payload["id"] = unscope_key(camera_id, tenant_id)
                    results.append(payload)
            return results

    def get_camera(self, camera_id: str, tenant_id: str = "default") -> dict[str, Any] | None:
        with self._lock, self.connection() as conn:
            scoped_id = scope_key(tenant_id, camera_id)
            row = conn.execute(
                """
                SELECT id, name, camera_role, department_id, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras
                WHERE id = ?
                """,
                (scoped_id,),
            ).fetchone()
            if row:
                payload = dict(row)
                payload["id"] = unscope_key(str(payload["id"]), tenant_id)
                return payload
            if normalize_tenant_id(tenant_id) == "default":
                row = conn.execute(
                    """
                    SELECT id, name, camera_role, department_id, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                    FROM cameras
                    WHERE id = ?
                    """,
                    (camera_id,),
                ).fetchone()
                if row:
                    return dict(row)
            return None

    def upsert_camera(self, camera: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
        camera_id = str(camera.get("id") or "").strip() or self._generate_id()
        scoped_id = scope_key(tenant_id, camera_id)
        name = str(camera.get("name") or camera_id).strip()
        camera_role = str(camera.get("cameraRole") or camera.get("camera_role") or "general").strip().lower()
        if camera_role not in {"general", "check_in", "check_out"}:
            camera_role = "general"
        department_id = self._clean_optional(camera.get("departmentId") or camera.get("department_id"))
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
                INSERT INTO cameras (id, name, camera_role, department_id, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    camera_role = excluded.camera_role,
                    department_id = excluded.department_id,
                    rtsp_url = excluded.rtsp_url,
                    rtsp_username = excluded.rtsp_username,
                    rtsp_password = excluded.rtsp_password,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (scoped_id, name, camera_role, department_id, rtsp_url, rtsp_username, rtsp_password, enabled, now, now),
            )
            row = conn.execute(
                """
                SELECT id, name, camera_role, department_id, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras
                WHERE id = ?
                """,
                (scoped_id,),
            ).fetchone()
            if row is None:
                return {
                    "id": camera_id,
                    "name": name,
                    "camera_role": camera_role,
                    "department_id": department_id,
                    "rtsp_url": rtsp_url,
                    "rtsp_username": rtsp_username,
                    "rtsp_password": rtsp_password,
                    "enabled": enabled,
                    "created_at": now,
                    "updated_at": now,
                }
            payload = dict(row)
            payload["id"] = unscope_key(str(payload["id"]), tenant_id)
            return payload

    def delete_camera(self, camera_id: str, tenant_id: str = "default") -> bool:
        with self._lock, self.connection() as conn:
            deleted = conn.execute("DELETE FROM cameras WHERE id = ?", (scope_key(tenant_id, camera_id),)).rowcount
            if deleted == 0 and normalize_tenant_id(tenant_id) == "default":
                deleted = conn.execute("DELETE FROM cameras WHERE id = ?", (camera_id,)).rowcount
            return deleted > 0

    def get_default_camera(self, tenant_id: str = "default") -> dict[str, Any] | None:
        with self._lock, self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, name, camera_role, department_id, rtsp_url, rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras
                WHERE enabled = 1
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            payload = dict(row)
            payload["id"] = unscope_key(str(payload["id"]), tenant_id)
            return payload

    def list_departments(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, tenant_id, name, description, created_at, updated_at
                FROM departments
                WHERE tenant_id = ?
                ORDER BY name COLLATE NOCASE
                """,
                (tenant,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_department(self, department_id: str | None, tenant_id: str = "default") -> dict[str, Any] | None:
        if not department_id:
            return None
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "SELECT id, tenant_id, name, description, created_at, updated_at FROM departments WHERE id = ? AND tenant_id = ?",
                (department_id, tenant),
            ).fetchone()
            return dict(row) if row else None

    def upsert_department(self, payload: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        department_id = str(payload.get("id") or "").strip() or f"dept-{int(time.time())}-{os.urandom(3).hex()}"
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Department name is required")
        description = self._clean_optional(payload.get("description"))
        now = iso_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO departments (id, tenant_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (department_id, tenant, name, description, now, now),
            )
            row = conn.execute("SELECT * FROM departments WHERE id = ?", (department_id,)).fetchone()
            return dict(row)

    def delete_department(self, department_id: str, tenant_id: str = "default") -> bool:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            deleted = conn.execute("DELETE FROM departments WHERE id = ? AND tenant_id = ?", (department_id, tenant)).rowcount
            conn.execute("DELETE FROM employee_departments WHERE department_id = ?", (department_id,))
            conn.execute("UPDATE cameras SET department_id = NULL WHERE department_id = ?", (department_id,))
            return deleted > 0

    def list_employees(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT e.id, e.tenant_id, e.name, e.employee_code, e.role, e.active, e.created_at, e.updated_at,
                       COUNT(fe.id) AS photoCount
                FROM employees e
                LEFT JOIN face_embeddings fe ON fe.employee_id = e.id
                WHERE e.tenant_id = ?
                GROUP BY e.id
                ORDER BY e.name COLLATE NOCASE
                """,
                (tenant,),
            ).fetchall()
            departments = self.employee_department_map(conn)
            result = []
            for row in rows:
                payload = dict(row)
                payload["departments"] = departments.get(str(row["id"]), [])
                result.append(payload)
            return result

    def employee_department_map(self, conn: sqlite3.Connection) -> dict[str, list[str]]:
        rows = conn.execute("SELECT employee_id, department_id FROM employee_departments").fetchall()
        result: dict[str, list[str]] = defaultdict(list)
        for row in rows:
            result[str(row["employee_id"])].append(str(row["department_id"]))
        return result

    def upsert_employee(self, payload: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        employee_id = str(payload.get("id") or "").strip() or f"emp-{int(time.time())}-{os.urandom(3).hex()}"
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Employee name is required")
        code = self._clean_optional(payload.get("employeeCode") or payload.get("employee_code"))
        role = self._clean_optional(payload.get("role"))
        active = 1 if bool(payload.get("active", True)) else 0
        department_ids = [str(value).strip() for value in payload.get("departmentIds", []) if str(value).strip()]
        now = iso_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO employees (id, tenant_id, name, employee_code, role, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    employee_code = excluded.employee_code,
                    role = excluded.role,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (employee_id, tenant, name, code, role, active, now, now),
            )
            conn.execute("DELETE FROM employee_departments WHERE employee_id = ?", (employee_id,))
            for department_id in department_ids:
                conn.execute(
                    "INSERT OR IGNORE INTO employee_departments (employee_id, department_id, created_at) VALUES (?, ?, ?)",
                    (employee_id, department_id, now),
                )
            row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
            payload = dict(row)
            payload["departments"] = department_ids
            return payload

    def delete_employee(self, employee_id: str, tenant_id: str = "default") -> bool:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            row = conn.execute("SELECT name FROM employees WHERE id = ? AND tenant_id = ?", (employee_id, tenant)).fetchone()
            deleted = conn.execute("DELETE FROM employees WHERE id = ? AND tenant_id = ?", (employee_id, tenant)).rowcount
            conn.execute("DELETE FROM employee_departments WHERE employee_id = ?", (employee_id,))
            conn.execute("DELETE FROM face_embeddings WHERE employee_id = ?", (employee_id,))
            if row:
                conn.execute("DELETE FROM known_faces WHERE label = ?", (scope_key(tenant, str(row["name"])),))
            conn.execute("DELETE FROM known_faces WHERE label NOT IN (SELECT DISTINCT label FROM face_embeddings)")
            return deleted > 0

    def cleanup_orphan_faces(self, tenant_id: str = "default") -> int:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            scoped = f"{tenant}::"
            if tenant == "default":
                cursor = conn.execute(
                    """
                    DELETE FROM face_embeddings
                    WHERE employee_id IS NULL
                       OR employee_id = ''
                       OR employee_id NOT IN (SELECT id FROM employees WHERE tenant_id = ?)
                    """,
                    (tenant,),
                )
            else:
                cursor = conn.execute(
                    """
                    DELETE FROM face_embeddings
                    WHERE label LIKE ?
                      AND (
                        employee_id IS NULL
                        OR employee_id = ''
                        OR employee_id NOT IN (SELECT id FROM employees WHERE tenant_id = ?)
                      )
                    """,
                    (f"{scoped}%", tenant),
                )
            conn.execute("DELETE FROM known_faces WHERE label NOT IN (SELECT DISTINCT label FROM face_embeddings)")
            return int(cursor.rowcount or 0)

    def clear_faces(self, tenant_id: str = "default") -> None:
        with self._lock, self.connection() as conn:
            prefix = f"{normalize_tenant_id(tenant_id)}::"
            if normalize_tenant_id(tenant_id) == "default":
                conn.execute("DELETE FROM face_embeddings WHERE label NOT LIKE '%::%' OR label LIKE ?", (f"{prefix}%",))
                conn.execute("DELETE FROM known_faces WHERE label NOT LIKE '%::%' OR label LIKE ?", (f"{prefix}%",))
            else:
                conn.execute("DELETE FROM face_embeddings WHERE label LIKE ?", (f"{prefix}%",))
                conn.execute("DELETE FROM known_faces WHERE label LIKE ?", (f"{prefix}%",))

    def remove_face(self, label: str, tenant_id: str = "default") -> bool:
        with self._lock, self.connection() as conn:
            scoped = scope_key(tenant_id, label)
            deleted = conn.execute("DELETE FROM known_faces WHERE label = ?", (scoped,)).rowcount
            if deleted == 0 and normalize_tenant_id(tenant_id) == "default":
                deleted = conn.execute("DELETE FROM known_faces WHERE label = ?", (label,)).rowcount
            return deleted > 0

    def list_faces(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT f.label, f.updated_at, COUNT(e.id) AS sampleCount
                FROM known_faces f
                JOIN face_embeddings e ON e.label = f.label
                JOIN employees emp ON emp.id = e.employee_id AND emp.tenant_id = ?
                GROUP BY f.label, f.updated_at
                ORDER BY f.label COLLATE NOCASE
                """,
                (tenant,),
            ).fetchall()
            scoped = f"{tenant}::"
            results = []
            for row in rows:
                label = str(row["label"])
                if label.startswith(scoped) or (tenant == "default" and "::" not in label):
                    payload = dict(row)
                    payload["label"] = unscope_key(label, tenant_id)
                    results.append(payload)
            return results

    def register_face(self, label: str, embedding: np.ndarray, tenant_id: str = "default", employee_id: str | None = None) -> dict[str, Any]:
        label = label.strip()
        if not label:
            raise HTTPException(status_code=400, detail="Label is required")
        stored_label = scope_key(tenant_id, label)
        normalized = normalize_embedding(embedding).astype(np.float32).tolist()
        now = iso_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO known_faces (label, updated_at)
                VALUES (?, ?)
                ON CONFLICT(label) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (stored_label, now),
            )
            conn.execute(
                """
                INSERT INTO face_embeddings (label, employee_id, embedding, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (stored_label, employee_id, json.dumps(normalized), now),
            )
            row = conn.execute(
                """
                SELECT f.label, f.updated_at, COUNT(e.id) AS sampleCount
                FROM known_faces f
                LEFT JOIN face_embeddings e ON e.label = f.label
                WHERE f.label = ?
                GROUP BY f.label, f.updated_at
                """,
                (stored_label,),
            ).fetchone()
            if row is None:
                return {
                    "label": label,
                    "updatedAt": now,
                    "sampleCount": 1,
                }
            payload = dict(row)
            payload["label"] = unscope_key(str(payload["label"]), tenant_id)
            return payload

    def all_embeddings(self, tenant_id: str = "default") -> list[tuple[str, np.ndarray, str, int, str | None, list[str], bool]]:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT f.label, e.employee_id, e.embedding, f.updated_at,
                       emp.name AS employee_name, emp.active AS employee_active,
                       GROUP_CONCAT(ed.department_id) AS department_ids
                FROM known_faces f
                JOIN face_embeddings e ON e.label = f.label
                JOIN employees emp ON emp.id = e.employee_id AND emp.tenant_id = ?
                LEFT JOIN employee_departments ed ON ed.employee_id = emp.id
                GROUP BY e.id
                ORDER BY f.label COLLATE NOCASE, e.id ASC
                """,
                (tenant,),
            ).fetchall()
            grouped: dict[str, tuple[str, list[tuple[np.ndarray, str | None, list[str], bool]], str]] = {}
            prefix = f"{tenant}::"
            for row in rows:
                stored_label = str(row["label"])
                if not (stored_label.startswith(prefix) or (tenant == "default" and "::" not in stored_label)):
                    continue
                embedding = np.asarray(json.loads(row["embedding"]), dtype=np.float32)
                updated_at = str(row["updated_at"])
                employee_id = str(row["employee_id"]) if row["employee_id"] else None
                label = str(row["employee_name"] or unscope_key(stored_label, tenant_id))
                group_key = employee_id or stored_label
                if group_key not in grouped:
                    grouped[group_key] = (label, [], updated_at)
                department_ids = [item for item in str(row["department_ids"] or "").split(",") if item]
                employee_active = bool(row["employee_active"]) if row["employee_active"] is not None else True
                grouped[group_key][1].append((embedding, employee_id, department_ids, employee_active))
            result: list[tuple[str, np.ndarray, str, int, str | None, list[str], bool]] = []
            for _group_key, (label, embeddings, updated_at) in grouped.items():
                for embedding, employee_id, department_ids, employee_active in embeddings:
                    result.append((label, embedding, updated_at, len(embeddings), employee_id, department_ids, employee_active))
            return result

    def record_attendance(
        self,
        label: str,
        confidence: float,
        timestamp: str,
        cooldown_ms: int,
        camera_role: str = "general",
        tenant_id: str = "default",
        camera_id: str | None = None,
        camera_name: str | None = None,
        department_id: str | None = None,
        department_name: str | None = None,
        snapshot_path: str | None = None,
    ) -> dict[str, Any]:
        role = camera_role if camera_role in {"general", "check_in", "check_out"} else "general"
        stored_label = scope_key(tenant_id, label)
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM attendance_records WHERE label = ?",
                (stored_label,),
            ).fetchone()
            if row is None:
                record = {
                    "label": label,
                    "first_appearance": timestamp,
                    "last_appearance": timestamp,
                    "first_camera_role": role,
                    "last_camera_role": role,
                    "first_camera_id": camera_id,
                    "last_camera_id": camera_id,
                    "first_camera_name": camera_name,
                    "last_camera_name": camera_name,
                    "first_department_id": department_id,
                    "last_department_id": department_id,
                    "first_department_name": department_name,
                    "last_department_name": department_name,
                    "first_snapshot_path": snapshot_path,
                    "last_snapshot_path": snapshot_path,
                    "last_confidence": float(confidence),
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
                    "first_camera_id": row["first_camera_id"],
                    "last_camera_id": camera_id,
                    "first_camera_name": row["first_camera_name"],
                    "last_camera_name": camera_name,
                    "first_department_id": row["first_department_id"],
                    "last_department_id": department_id,
                    "first_department_name": row["first_department_name"],
                    "last_department_name": department_name,
                    "first_snapshot_path": row["first_snapshot_path"],
                    "last_snapshot_path": snapshot_path or row["last_snapshot_path"],
                    "last_confidence": float(confidence),
                    "appearances": appearances,
                    "max_confidence": max(float(row["max_confidence"]), float(confidence)),
                }
            conn.execute(
                """
                INSERT INTO attendance_records (
                    label, first_appearance, last_appearance, first_camera_role, last_camera_role,
                    first_camera_id, last_camera_id, first_camera_name, last_camera_name,
                    first_department_id, last_department_id, first_department_name, last_department_name,
                    first_snapshot_path, last_snapshot_path, last_confidence, appearances, max_confidence
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(label) DO UPDATE SET
                    first_appearance = excluded.first_appearance,
                    last_appearance = excluded.last_appearance,
                    first_camera_role = excluded.first_camera_role,
                    last_camera_role = excluded.last_camera_role,
                    first_camera_id = excluded.first_camera_id,
                    last_camera_id = excluded.last_camera_id,
                    first_camera_name = excluded.first_camera_name,
                    last_camera_name = excluded.last_camera_name,
                    first_department_id = excluded.first_department_id,
                    last_department_id = excluded.last_department_id,
                    first_department_name = excluded.first_department_name,
                    last_department_name = excluded.last_department_name,
                    first_snapshot_path = excluded.first_snapshot_path,
                    last_snapshot_path = excluded.last_snapshot_path,
                    last_confidence = excluded.last_confidence,
                    appearances = excluded.appearances,
                    max_confidence = excluded.max_confidence
                """,
                (
                    stored_label,
                    record["first_appearance"],
                    record["last_appearance"],
                    record["first_camera_role"],
                    record["last_camera_role"],
                    record["first_camera_id"],
                    record["last_camera_id"],
                    record["first_camera_name"],
                    record["last_camera_name"],
                    record["first_department_id"],
                    record["last_department_id"],
                    record["first_department_name"],
                    record["last_department_name"],
                    record["first_snapshot_path"],
                    record["last_snapshot_path"],
                    record["last_confidence"],
                    record["appearances"],
                    record["max_confidence"],
                ),
            )
            return record

    def list_attendance(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM attendance_records
                ORDER BY last_appearance DESC, label COLLATE NOCASE
                """
            ).fetchall()
            results = []
            prefix = f"{normalize_tenant_id(tenant_id)}::"
            for row in rows:
                label = str(row["label"])
                if label.startswith(prefix) or (normalize_tenant_id(tenant_id) == "default" and "::" not in label):
                    payload = dict(row)
                    payload["label"] = unscope_key(label, tenant_id)
                    results.append(payload)
            return results

    def enqueue_sync_event(self, event_type: str, payload: dict[str, Any], tenant_id: str = "default") -> int:
        with self._lock, self.connection() as conn:
            row = conn.execute(
                """
                INSERT INTO sync_events (event_type, payload, created_at)
                VALUES (?, ?, ?)
                """,
                (event_type, json.dumps({**payload, "tenantId": normalize_tenant_id(tenant_id)}), iso_now()),
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

    def ensure_tenant(self, tenant_id: str, name: str | None = None) -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        tenant_name = str(name or tenant).strip() or tenant
        now = iso_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO tenants (id, name, status, created_at, updated_at)
                VALUES (?, ?, 'active', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    updated_at = excluded.updated_at
                """,
                (tenant, tenant_name, now, now),
            )
            row = conn.execute(
                "SELECT id, name, status, created_at, updated_at FROM tenants WHERE id = ?",
                (tenant,),
            ).fetchone()
            return dict(row) if row else {
                "id": tenant,
                "name": tenant_name,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }

    def upsert_license(self, tenant_id: str, license_key: str, plan: str = "local", cloud_sync_enabled: bool = False, expires_at: str | None = None) -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        key = str(license_key).strip()
        if not key:
            raise HTTPException(status_code=400, detail="licenseKey is required")
        now = iso_now()
        license_id = f"lic-{tenant}-{hashlib.sha1(key.encode('utf-8')).hexdigest()[:10]}"
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO licenses (id, tenant_id, license_key, plan, status, cloud_sync_enabled, expires_at, activated_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, license_key) DO UPDATE SET
                    plan = excluded.plan,
                    status = excluded.status,
                    cloud_sync_enabled = excluded.cloud_sync_enabled,
                    expires_at = excluded.expires_at,
                    updated_at = excluded.updated_at
                """,
                (license_id, tenant, key, plan, 1 if cloud_sync_enabled else 0, expires_at, now, now, now),
            )
            row = conn.execute(
                """
                SELECT id, tenant_id, license_key, plan, status, cloud_sync_enabled, expires_at, activated_at, created_at, updated_at
                FROM licenses
                WHERE tenant_id = ? AND license_key = ?
                """,
                (tenant, key),
            ).fetchone()
            return dict(row) if row else {}

    def get_license(self, tenant_id: str) -> dict[str, Any] | None:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, tenant_id, license_key, plan, status, cloud_sync_enabled, expires_at, activated_at, created_at, updated_at
                FROM licenses
                WHERE tenant_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (tenant,),
            ).fetchone()
            return dict(row) if row else None

    def create_user(self, tenant_id: str, email: str, password: str, role: str = "admin") -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        now = iso_now()
        user_id = f"user-{tenant}-{secrets.token_hex(4)}"
        password_hash = self._hash_password(password)
        email_value = str(email).strip().lower()
        if not email_value:
            raise HTTPException(status_code=400, detail="email is required")
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, tenant_id, email, password_hash, role, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(tenant_id, email) DO UPDATE SET
                    password_hash = excluded.password_hash,
                    role = excluded.role,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (user_id, tenant, email_value, password_hash, role or "admin", now, now),
            )
            row = conn.execute(
                """
                SELECT id, tenant_id, email, role, enabled, created_at, updated_at
                FROM users
                WHERE tenant_id = ? AND email = ?
                """,
                (tenant, email_value),
            ).fetchone()
            payload = dict(row) if row else {}
            if payload:
                payload["email"] = email_value
            return payload

    def authenticate_user(self, tenant_id: str, email: str, password: str) -> dict[str, Any] | None:
        tenant = normalize_tenant_id(tenant_id)
        email_value = str(email).strip().lower()
        with self._lock, self.connection() as conn:
            row = conn.execute(
                """
                SELECT id, tenant_id, email, password_hash, role, enabled, created_at, updated_at
                FROM users
                WHERE tenant_id = ? AND email = ?
                """,
                (tenant, email_value),
            ).fetchone()
            if row is None:
                return None
            if not bool(row["enabled"]):
                return None
            if not self._verify_password(password, str(row["password_hash"])):
                return None
            payload = dict(row)
            payload.pop("password_hash", None)
            return payload

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
        return f"{salt}${digest.hex()}"

    def _verify_password(self, password: str, stored: str) -> bool:
        try:
            salt, digest = stored.split("$", 1)
        except ValueError:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
        return secrets.compare_digest(candidate, digest)

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
        self._last_alarm_at = 0.0
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
                    "processedFrames": 0,
                    "droppedFrames": 0,
                    "lastFaces": [],
                    "lastDetection": None,
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
        if snapshot is not None:
            state = "snapshot saved"
            self._last_detection = snapshot
        camera_key = camera_id or camera_role or "general"
        known_faces = [face for face in detected if face["match"] and face["match"].get("label")]
        unknown_faces = [face for face in detected if not face["match"] or not face["match"].get("label")]
        unknown_faces = [face for face in unknown_faces if float(face.get("confidence") or 0.0) >= self.alarm_min_detection_confidence]
        unknown_faces = [face for face in unknown_faces if self._is_alertworthy_face(face, image.shape)]
        self._update_camera_alarm_state(camera_key, known_faces, unknown_faces)
        should_alarm = self._should_alarm_camera(camera_key, unknown_faces)
        if unknown_faces:
            if should_alarm:
                self._trigger_alarm(
                    image,
                    camera_role,
                    camera_id,
                    "unknown_person",
                    unknown_faces,
                    snapshot,
                )
        camera_record = self.store.get_camera(camera_id, tenant) if camera_id else None
        camera_name = str(camera_record.get("name") or "") if camera_record else None
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
                "label": sample.label,
                "sampleCount": sample.sample_count,
                "updatedAt": sample.updatedAt,
                "cameraRole": camera_role,
                "cameraId": camera_id,
            },
            tenant,
        )
        return {
            "label": sample.label,
            "sampleCount": sample.sample_count,
            "updatedAt": sample.updatedAt,
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
                        logger.debug("Frame processed: %s", {"cameraId": camera_id, "state": result.get("state")})
                    except Exception as exc:  # noqa: BLE001
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
        match = raw_match if raw_match and raw_match.get("authorized", True) else None
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
            if employee_id and camera_department_id:
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

    def _trigger_alarm(
        self,
        image: np.ndarray,
        camera_role: str,
        camera_id: str | None,
        reason: str,
        faces: list[dict[str, Any]],
        snapshot: dict[str, Any] | None,
    ) -> None:
        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0
        with self._snapshot_lock:
            if now_ms - self._last_alarm_at < self.alarm_cooldown_ms:
                return
            self._last_alarm_at = now_ms

        camera_key = camera_id or camera_role or "general"
        camera_state = self._camera_alarm_state[camera_key]
        camera_state["last_alarm_at"] = now_ms
        camera_state["unknown_streak"] = 0
        camera_state["suppress_alarm_until"] = now_ms + 2_000

        alarm_record = {
            "reason": reason,
            "cameraRole": camera_role,
            "cameraId": camera_id,
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
