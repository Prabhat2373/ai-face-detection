"""Database access layer for the FaceAgent desktop UI.

This module is a **thin wrapper** around ``SQLiteStore`` from the Python
backend (``python_recognizer.app``).  All schema management, SQL queries,
and business logic live in the backend — the UI only calls store methods
and adapts the results for its pages.
"""

import os
import sys
from typing import Any, Optional
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import the backend.
# ---------------------------------------------------------------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Import from the lightweight store (no cv2/FastAPI/InsightFace deps).
from python_recognizer.store import SQLiteStore  # noqa: E402
from ui.backend_process import writable_app_dir  # noqa: E402

_DEFAULT_TENANT = "default"

# Path to the backend's database
_BACKEND_DB = os.getenv("PYTHON_DB_PATH") or str(writable_app_dir() / "data" / "app.db")


class Database:
    """Singleton façade that delegates every operation to the backend's
    ``SQLiteStore``.  The public API matches what every UI page expects."""

    _instance: Optional["Database"] = None

    def __init__(self, db_path: str = _BACKEND_DB):
        self._store = SQLiteStore(Path(db_path))
        self._store.ensure_tenant(_DEFAULT_TENANT, "Local Tenant")
        self.db_path = db_path

    @classmethod
    def get(cls) -> "Database":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Cameras ─────────────────────────────────────────────────────────

    def list_cameras(self) -> list[dict]:
        return self._store.list_cameras(_DEFAULT_TENANT)

    def get_camera(self, camera_id: str) -> Optional[dict]:
        return self._store.get_camera(camera_id, _DEFAULT_TENANT)

    def save_camera(self, data: dict) -> dict:
        """Adapt the UI dialog format to the backend's ``upsert_camera``."""
        return self._store.upsert_camera(data, _DEFAULT_TENANT)

    def delete_camera(self, camera_id: str) -> bool:
        return self._store.delete_camera(camera_id, _DEFAULT_TENANT)

    # ── Known Faces ─────────────────────────────────────────────────────

    def list_known_faces(self) -> list[dict]:
        return self._store.list_faces(_DEFAULT_TENANT)

    def remove_known_face(self, label: str) -> bool:
        return self._store.remove_face(label, _DEFAULT_TENANT)

    # ── Departments ─────────────────────────────────────────────────────

    def list_departments(self) -> list[dict]:
        """Return departments with an ``employee_count`` field so existing
        pages keep working."""
        depts = self._store.list_departments(_DEFAULT_TENANT)
        # Enrich with employee counts via the junction table.
        conn = self._store.connection()
        try:
            for dept in depts:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM employee_departments WHERE department_id = ?",
                    (dept["id"],),
                ).fetchone()
                dept["employee_count"] = row["c"] if row else 0
        finally:
            conn.close()
        return depts

    def get_department(self, dept_id: str) -> Optional[dict]:
        return self._store.get_department(dept_id, _DEFAULT_TENANT)

    def save_department(self, data: dict) -> dict:
        return self._store.upsert_department(data, _DEFAULT_TENANT)

    def delete_department(self, dept_id: str) -> bool:
        return self._store.delete_department(dept_id, _DEFAULT_TENANT)

    # ── Employees ───────────────────────────────────────────────────────

    def list_employees(self) -> list[dict]:
        """Return employees enriched with ``department_id`` and
        ``department_name`` so existing pages keep working."""
        emps = self._store.list_employees(_DEFAULT_TENANT)
        conn = self._store.connection()
        try:
            for emp in emps:
                dept_ids = emp.get("departments") or []
                emp["department_id"] = dept_ids[0] if dept_ids else None
                if dept_ids:
                    row = conn.execute(
                        "SELECT name FROM departments WHERE id = ? AND tenant_id = ?",
                        (dept_ids[0], _DEFAULT_TENANT),
                    ).fetchone()
                    emp["department_name"] = row["name"] if row else ""
                else:
                    emp["department_name"] = ""
        finally:
            conn.close()
        return emps

    def get_employee(self, emp_id: str) -> Optional[dict]:
        emps = self._store.list_employees(_DEFAULT_TENANT)
        return next((e for e in emps if e["id"] == emp_id), None)

    def save_employee(self, data: dict) -> dict:
        """Adapt the UI dialog format (``department_id``) to the backend
        format (``departmentIds`` list)."""
        payload: dict[str, Any] = {
            "name": data.get("name", ""),
            "employeeCode": data.get("employee_code", ""),
            "role": data.get("role", ""),
            "active": data.get("active", True),
        }
        if data.get("id"):
            payload["id"] = data["id"]
        dept_id = data.get("department_id")
        payload["departmentIds"] = [dept_id] if dept_id else []
        return self._store.upsert_employee(payload, _DEFAULT_TENANT)

    def delete_employee(self, emp_id: str) -> bool:
        return self._store.delete_employee(emp_id, _DEFAULT_TENANT)

    # ── Attendance ──────────────────────────────────────────────────────

    def list_attendance(self, attendance_date: str | None = None) -> list[dict]:
        records = self._store.list_attendance(_DEFAULT_TENANT)
        if attendance_date:
            return [
                record for record in records
                if str(record.get("attendance_date") or record.get("last_appearance", "")[:10]) == attendance_date
            ]
        return records

    def recent_attendance(self, limit: int = 10) -> list[dict]:
        return self.list_attendance()[:limit]

    # ── Dashboard stats ─────────────────────────────────────────────────

    def dashboard_stats(self) -> dict:
        cameras = self._store.list_cameras(_DEFAULT_TENANT)
        departments = self._store.list_departments(_DEFAULT_TENANT)
        employees = self._store.list_employees(_DEFAULT_TENANT)
        faces = self._store.list_faces(_DEFAULT_TENANT)
        attendance = self._store.list_attendance(_DEFAULT_TENANT)
        return {
            "active_cameras": sum(1 for c in cameras if c.get("enabled")),
            "active_employees": sum(1 for e in employees if e.get("active")),
            "departments": len(departments),
            "known_faces": len(faces),
            "total_attendance": len(attendance),
        }

    # ── Sync events (used by alarms page) ───────────────────────────────

    def list_sync_events(self, limit: int = 100) -> list[dict]:
        return self._store.list_sync_events(limit)

    def list_all_sync_events(self, limit: int = 20) -> list[dict]:
        return self._store.list_all_sync_events(limit)

    def clear_sync_events(self) -> None:
        self._store.clear_sync_events()
