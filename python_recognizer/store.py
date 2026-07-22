"""Lightweight database store for the FaceAgent backend.

This module contains **only** the SQLite data-access layer with zero heavy
dependencies (no OpenCV, no FastAPI, no InsightFace).  Both the Python
backend (``app.py``) and the PySide6 desktop UI import from here.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import secrets
import sqlite3
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def normalize_tenant_id(value: str | None) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return "default"
    cleaned = [char if char.isalnum() or char in {"-", "_"} else "-" for char in text]
    return "".join(cleaned)[:80] or "default"


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


def unscope_key(value: str, tenant_id: str) -> str:
    tenant = normalize_tenant_id(tenant_id)
    prefix = f"{tenant}::"
    if value.startswith(prefix):
        return value[len(prefix):]
    if tenant == "default" and "::" not in value:
        return value
    return value


def normalize_embedding(embedding: Any) -> Any:
    """Normalize a numpy-like embedding vector.  Requires numpy at call-time
    only if the input is a numpy array; otherwise returns as-is."""
    try:
        import numpy as np

        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(vector))
        if not math.isfinite(norm) or norm <= 0:
            return vector
        return vector / norm
    except ImportError:
        return embedding


# ---------------------------------------------------------------------------
# SQLiteStore
# ---------------------------------------------------------------------------

class SQLiteStore:
    """Thread-safe SQLite store for all application data."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = threading.RLock()
        self._ensure_schema()

    def connection(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Schema ──────────────────────────────────────────────────────────

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
                    person_label TEXT,
                    attendance_date TEXT,
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
            self._ensure_column(conn, "attendance_records", "person_label", "TEXT")
            self._ensure_column(conn, "attendance_records", "attendance_date", "TEXT")
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

    # ── Cameras ─────────────────────────────────────────────────────────

    def list_cameras(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT id, name, camera_role, department_id, rtsp_url,
                       rtsp_username, rtsp_password, enabled, created_at, updated_at
                FROM cameras ORDER BY created_at ASC
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
                "SELECT * FROM cameras WHERE id = ?", (scoped_id,)
            ).fetchone()
            if row:
                payload = dict(row)
                payload["id"] = unscope_key(str(payload["id"]), tenant_id)
                return payload
            if normalize_tenant_id(tenant_id) == "default":
                row = conn.execute(
                    "SELECT * FROM cameras WHERE id = ?", (camera_id,)
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
            raise ValueError("rtspUrl is required")
        rtsp_username = self._clean_optional(camera.get("rtspUsername") or camera.get("rtsp_username"))
        rtsp_password = self._clean_optional(camera.get("rtspPassword") or camera.get("rtsp_password"))
        enabled = 1 if bool(camera.get("enabled", True)) else 0
        now = iso_now()

        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO cameras (id, name, camera_role, department_id, rtsp_url,
                                     rtsp_username, rtsp_password, enabled, created_at, updated_at)
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
                (scoped_id, name, camera_role, department_id, rtsp_url,
                 rtsp_username, rtsp_password, enabled, now, now),
            )
            row = conn.execute(
                "SELECT * FROM cameras WHERE id = ?", (scoped_id,)
            ).fetchone()
            if row is None:
                return {
                    "id": camera_id, "name": name, "camera_role": camera_role,
                    "department_id": department_id, "rtsp_url": rtsp_url,
                    "rtsp_username": rtsp_username, "rtsp_password": rtsp_password,
                    "enabled": enabled, "created_at": now, "updated_at": now,
                }
            payload = dict(row)
            payload["id"] = unscope_key(str(payload["id"]), tenant_id)
            return payload

    def delete_camera(self, camera_id: str, tenant_id: str = "default") -> bool:
        with self._lock, self.connection() as conn:
            deleted = conn.execute(
                "DELETE FROM cameras WHERE id = ?", (scope_key(tenant_id, camera_id),)
            ).rowcount
            if deleted == 0 and normalize_tenant_id(tenant_id) == "default":
                deleted = conn.execute(
                    "DELETE FROM cameras WHERE id = ?", (camera_id,)
                ).rowcount
            return deleted > 0

    def get_default_camera(self, tenant_id: str = "default") -> dict[str, Any] | None:
        with self._lock, self.connection() as conn:
            row = conn.execute(
                """SELECT * FROM cameras WHERE enabled = 1
                   ORDER BY created_at ASC LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            payload = dict(row)
            payload["id"] = unscope_key(str(payload["id"]), tenant_id)
            return payload

    # ── Departments ─────────────────────────────────────────────────────

    def list_departments(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                "SELECT id, tenant_id, name, description, created_at, updated_at "
                "FROM departments WHERE tenant_id = ? ORDER BY name COLLATE NOCASE",
                (tenant,),
            ).fetchall()
            return [dict(row) for row in rows]

    def get_department(self, department_id: str | None, tenant_id: str = "default") -> dict[str, Any] | None:
        if not department_id:
            return None
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM departments WHERE id = ? AND tenant_id = ?",
                (department_id, tenant),
            ).fetchone()
            return dict(row) if row else None

    def department_employee_count(self, department_id: str) -> int:
        """Return the number of employees linked to a department."""
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM employee_departments WHERE department_id = ?",
                (department_id,),
            ).fetchone()
            return row["c"] if row else 0

    def upsert_department(self, payload: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        department_id = str(payload.get("id") or "").strip() or f"dept-{int(time.time())}-{os.urandom(3).hex()}"
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValueError("Department name is required")
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
            deleted = conn.execute(
                "DELETE FROM departments WHERE id = ? AND tenant_id = ?", (department_id, tenant)
            ).rowcount
            conn.execute("DELETE FROM employee_departments WHERE department_id = ?", (department_id,))
            conn.execute("UPDATE cameras SET department_id = NULL WHERE department_id = ?", (department_id,))
            return deleted > 0

    # ── Employees ───────────────────────────────────────────────────────

    def list_employees(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT e.id, e.tenant_id, e.name, e.employee_code, e.role,
                       e.active, e.created_at, e.updated_at,
                       COUNT(fe.id) AS photoCount
                FROM employees e
                LEFT JOIN face_embeddings fe ON fe.employee_id = e.id
                WHERE e.tenant_id = ?
                GROUP BY e.id
                ORDER BY e.name COLLATE NOCASE
                """,
                (tenant,),
            ).fetchall()
            departments = self._employee_department_map(conn)
            result = []
            for row in rows:
                payload = dict(row)
                payload["departments"] = departments.get(str(row["id"]), [])
                result.append(payload)
            return result

    def _employee_department_map(self, conn: sqlite3.Connection) -> dict[str, list[str]]:
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
            raise ValueError("Employee name is required")
        code = self._clean_optional(payload.get("employeeCode") or payload.get("employee_code"))
        role = self._clean_optional(payload.get("role"))
        active = 1 if bool(payload.get("active", True)) else 0
        department_ids = [str(v).strip() for v in payload.get("departmentIds", []) if str(v).strip()]
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
                    "INSERT OR IGNORE INTO employee_departments (employee_id, department_id, created_at) "
                    "VALUES (?, ?, ?)",
                    (employee_id, department_id, now),
                )
            row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
            result = dict(row) if row else {}
            result["departments"] = department_ids
            return result

    def delete_employee(self, employee_id: str, tenant_id: str = "default") -> bool:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "SELECT name FROM employees WHERE id = ? AND tenant_id = ?", (employee_id, tenant)
            ).fetchone()
            deleted = conn.execute(
                "DELETE FROM employees WHERE id = ? AND tenant_id = ?", (employee_id, tenant)
            ).rowcount
            conn.execute("DELETE FROM employee_departments WHERE employee_id = ?", (employee_id,))
            conn.execute("DELETE FROM face_embeddings WHERE employee_id = ?", (employee_id,))
            if row:
                conn.execute(
                    "DELETE FROM known_faces WHERE label = ?",
                    (scope_key(tenant, str(row["name"])),),
                )
            conn.execute(
                "DELETE FROM known_faces WHERE label NOT IN (SELECT DISTINCT label FROM face_embeddings)"
            )
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
            conn.execute(
                "DELETE FROM known_faces WHERE label NOT IN (SELECT DISTINCT label FROM face_embeddings)"
            )
            return int(cursor.rowcount or 0)

    # ── Known Faces ─────────────────────────────────────────────────────

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

    def register_face(self, label: str, embedding: Any, tenant_id: str = "default", employee_id: str | None = None) -> dict[str, Any]:
        label = label.strip()
        if not label:
            raise ValueError("Label is required")
        stored_label = scope_key(tenant_id, label)
        normalized = normalize_embedding(embedding)
        import numpy as np
        normalized = np.asarray(normalized, dtype=np.float32).tolist()
        now = iso_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO known_faces (label, updated_at) VALUES (?, ?)
                ON CONFLICT(label) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (stored_label, now),
            )
            conn.execute(
                "INSERT INTO face_embeddings (label, employee_id, embedding, created_at) VALUES (?, ?, ?, ?)",
                (stored_label, employee_id, json.dumps(normalized), now),
            )
            row = conn.execute(
                """
                SELECT f.label, f.updated_at, COUNT(e.id) AS sampleCount
                FROM known_faces f LEFT JOIN face_embeddings e ON e.label = f.label
                WHERE f.label = ? GROUP BY f.label, f.updated_at
                """,
                (stored_label,),
            ).fetchone()
            if row is None:
                return {"label": label, "updatedAt": now, "sampleCount": 1}
            payload = dict(row)
            payload["label"] = unscope_key(str(payload["label"]), tenant_id)
            return payload

    def remove_face(self, label: str, tenant_id: str = "default") -> bool:
        with self._lock, self.connection() as conn:
            scoped = scope_key(tenant_id, label)
            deleted = conn.execute("DELETE FROM known_faces WHERE label = ?", (scoped,)).rowcount
            if deleted == 0 and normalize_tenant_id(tenant_id) == "default":
                deleted = conn.execute("DELETE FROM known_faces WHERE label = ?", (label,)).rowcount
            return deleted > 0

    def clear_faces(self, tenant_id: str = "default") -> None:
        with self._lock, self.connection() as conn:
            prefix = f"{normalize_tenant_id(tenant_id)}::"
            if normalize_tenant_id(tenant_id) == "default":
                conn.execute(
                    "DELETE FROM face_embeddings WHERE label NOT LIKE '%::%' OR label LIKE ?",
                    (f"{prefix}%",),
                )
                conn.execute(
                    "DELETE FROM known_faces WHERE label NOT LIKE '%::%' OR label LIKE ?",
                    (f"{prefix}%",),
                )
            else:
                conn.execute("DELETE FROM face_embeddings WHERE label LIKE ?", (f"{prefix}%",))
                conn.execute("DELETE FROM known_faces WHERE label LIKE ?", (f"{prefix}%",))

    def all_embeddings(self, tenant_id: str = "default") -> list[tuple[str, Any, str, int, str | None, list[str], bool]]:
        import numpy as np

        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                """
                SELECT f.label, e.employee_id, e.embedding, f.updated_at,
                       emp.name AS employee_name, emp.active AS employee_active,
                       GROUP_CONCAT(ed.department_id) AS department_ids
                FROM known_faces f
                JOIN face_embeddings e ON e.label = f.label
                LEFT JOIN employees emp ON emp.id = e.employee_id
                LEFT JOIN employee_departments ed ON ed.employee_id = emp.id
                GROUP BY e.id
                ORDER BY f.label COLLATE NOCASE, e.id ASC
                """
            ).fetchall()
            grouped: dict[str, tuple[str, list[tuple[Any, str | None, list[str], bool]], str]] = {}
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
            result: list[tuple[str, Any, str, int, str | None, list[str], bool]] = []
            for _group_key, (label, embeddings, updated_at) in grouped.items():
                for embedding, employee_id, department_ids, employee_active in embeddings:
                    result.append((label, embedding, updated_at, len(embeddings), employee_id, department_ids, employee_active))
            return result

    # ── Attendance ──────────────────────────────────────────────────────

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
        tenant = normalize_tenant_id(tenant_id)
        attendance_date = timestamp[:10]
        stored_label = f"{tenant}::{label}::{attendance_date}"
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM attendance_records WHERE label = ?", (stored_label,)
            ).fetchone()
            if row is None:
                record = {
                    "label": label,
                    "person_label": label,
                    "attendance_date": attendance_date,
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
                try:
                    previous_last = datetime.fromisoformat(str(row["last_appearance"]).replace("Z", "+00:00"))
                    current = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
                    seconds = (current - previous_last).total_seconds()
                    if seconds * 1000.0 >= cooldown_ms:
                        appearances = int(row["appearances"]) + 1
                    else:
                        appearances = int(row["appearances"])
                except Exception:
                    appearances = int(row["appearances"]) + 1
                first_role = str(row["first_camera_role"] or "general")
                record = {
                    "label": label,
                    "person_label": str(row["person_label"] or label),
                    "attendance_date": str(row["attendance_date"] or attendance_date),
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
                    label, person_label, attendance_date,
                    first_appearance, last_appearance, first_camera_role, last_camera_role,
                    first_camera_id, last_camera_id, first_camera_name, last_camera_name,
                    first_department_id, last_department_id, first_department_name, last_department_name,
                    first_snapshot_path, last_snapshot_path, last_confidence, appearances, max_confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(label) DO UPDATE SET
                    person_label = excluded.person_label,
                    attendance_date = excluded.attendance_date,
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
                    record["person_label"], record["attendance_date"],
                    record["first_appearance"], record["last_appearance"],
                    record["first_camera_role"], record["last_camera_role"],
                    record["first_camera_id"], record["last_camera_id"],
                    record["first_camera_name"], record["last_camera_name"],
                    record["first_department_id"], record["last_department_id"],
                    record["first_department_name"], record["last_department_name"],
                    record["first_snapshot_path"], record["last_snapshot_path"],
                    record["last_confidence"], record["appearances"], record["max_confidence"],
                ),
            )
            return record

    def list_attendance(self, tenant_id: str = "default") -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM attendance_records ORDER BY last_appearance DESC, label COLLATE NOCASE"
            ).fetchall()
            results = []
            prefix = f"{normalize_tenant_id(tenant_id)}::"
            for row in rows:
                label = str(row["label"])
                if label.startswith(prefix) or (normalize_tenant_id(tenant_id) == "default" and "::" not in label):
                    payload = dict(row)
                    display_label = payload.get("person_label")
                    if not display_label:
                        display_label = unscope_key(label, tenant_id).rsplit("::", 1)[0]
                    payload["label"] = display_label
                    results.append(payload)
            return results

    # ── Sync Events ─────────────────────────────────────────────────────

    def enqueue_sync_event(self, event_type: str, payload: dict[str, Any], tenant_id: str = "default") -> int:
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "INSERT INTO sync_events (event_type, payload, created_at) VALUES (?, ?, ?)",
                (event_type, json.dumps({**payload, "tenantId": normalize_tenant_id(tenant_id)}), iso_now()),
            )
            return int(row.lastrowid)

    def list_sync_events(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                "SELECT id, event_type, payload, created_at, synced_at, retry_count, last_error "
                "FROM sync_events WHERE synced_at IS NULL ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_all_sync_events(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent sync events (synced or not) for the alarms page."""
        with self._lock, self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM sync_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def mark_sync_events_synced(self, ids: list[int]) -> None:
        if not ids:
            return
        placeholders = ",".join(["?"] * len(ids))
        with self._lock, self.connection() as conn:
            conn.execute(
                f"UPDATE sync_events SET synced_at = ?, last_error = NULL WHERE id IN ({placeholders})",
                [iso_now(), *ids],
            )

    def mark_sync_event_failed(self, event_id: int, error_message: str) -> None:
        with self._lock, self.connection() as conn:
            conn.execute(
                "UPDATE sync_events SET retry_count = retry_count + 1, last_error = ? WHERE id = ?",
                (error_message[:500], event_id),
            )

    def clear_sync_events(self) -> None:
        with self._lock, self.connection() as conn:
            conn.execute("DELETE FROM sync_events")

    # ── Tenants / Users / Licenses ──────────────────────────────────────

    def ensure_tenant(self, tenant_id: str, name: str | None = None) -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        tenant_name = str(name or tenant).strip() or tenant
        now = iso_now()
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO tenants (id, name, status, created_at, updated_at)
                VALUES (?, ?, 'active', ?, ?)
                ON CONFLICT(id) DO UPDATE SET name = excluded.name, updated_at = excluded.updated_at
                """,
                (tenant, tenant_name, now, now),
            )
            row = conn.execute(
                "SELECT * FROM tenants WHERE id = ?", (tenant,)
            ).fetchone()
            return dict(row) if row else {"id": tenant, "name": tenant_name, "status": "active", "created_at": now, "updated_at": now}

    def upsert_license(self, tenant_id: str, license_key: str, plan: str = "local",
                       cloud_sync_enabled: bool = False, expires_at: str | None = None) -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        key = str(license_key).strip()
        if not key:
            raise ValueError("licenseKey is required")
        now = iso_now()
        license_id = f"lic-{tenant}-{hashlib.sha1(key.encode()).hexdigest()[:10]}"
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO licenses (id, tenant_id, license_key, plan, status, cloud_sync_enabled,
                                      expires_at, activated_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
                ON CONFLICT(tenant_id, license_key) DO UPDATE SET
                    plan = excluded.plan, status = excluded.status,
                    cloud_sync_enabled = excluded.cloud_sync_enabled,
                    expires_at = excluded.expires_at, updated_at = excluded.updated_at
                """,
                (license_id, tenant, key, plan, 1 if cloud_sync_enabled else 0, expires_at, now, now, now, now),
            )
            row = conn.execute(
                "SELECT * FROM licenses WHERE tenant_id = ? AND license_key = ?", (tenant, key)
            ).fetchone()
            return dict(row) if row else {}

    def get_license(self, tenant_id: str) -> dict[str, Any] | None:
        tenant = normalize_tenant_id(tenant_id)
        with self._lock, self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM licenses WHERE tenant_id = ? ORDER BY created_at DESC LIMIT 1", (tenant,)
            ).fetchone()
            return dict(row) if row else None

    def create_user(self, tenant_id: str, email: str, password: str, role: str = "admin") -> dict[str, Any]:
        tenant = normalize_tenant_id(tenant_id)
        now = iso_now()
        user_id = f"user-{tenant}-{secrets.token_hex(4)}"
        password_hash = self._hash_password(password)
        email_value = str(email).strip().lower()
        if not email_value:
            raise ValueError("email is required")
        with self._lock, self.connection() as conn:
            conn.execute(
                """
                INSERT INTO users (id, tenant_id, email, password_hash, role, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(tenant_id, email) DO UPDATE SET
                    password_hash = excluded.password_hash, role = excluded.role,
                    enabled = excluded.enabled, updated_at = excluded.updated_at
                """,
                (user_id, tenant, email_value, password_hash, role or "admin", now, now),
            )
            row = conn.execute(
                "SELECT id, tenant_id, email, role, enabled, created_at, updated_at "
                "FROM users WHERE tenant_id = ? AND email = ?", (tenant, email_value)
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
                "SELECT * FROM users WHERE tenant_id = ? AND email = ?", (tenant, email_value)
            ).fetchone()
            if row is None or not bool(row["enabled"]):
                return None
            if not self._verify_password(password, str(row["password_hash"])):
                return None
            payload = dict(row)
            payload.pop("password_hash", None)
            return payload

    # ── Internal helpers ────────────────────────────────────────────────

    def _hash_password(self, password: str) -> str:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
        return f"{salt}${digest.hex()}"

    def _verify_password(self, password: str, stored: str) -> bool:
        try:
            salt, digest = stored.split("$", 1)
        except ValueError:
            return False
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
        return secrets.compare_digest(candidate, digest)

    def _generate_id(self) -> str:
        return f"cam-{int(time.time())}-{os.urandom(3).hex()}"

    def _clean_optional(self, value: Any) -> str | None:
        text = str(value).strip() if value is not None else ""
        return text or None
