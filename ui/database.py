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
from python_recognizer.store import SQLiteStore, get_canonical_db_path  # noqa: E402
from ui.backend_process import writable_app_dir  # noqa: E402

_DEFAULT_TENANT = "default"

def _resolve_backend_db() -> str:
    return str(get_canonical_db_path())

_BACKEND_DB = _resolve_backend_db()


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

    def get_setting(self, key: str, default: str) -> str:
        return self._store.get_setting(key, default)

    def set_setting(self, key: str, value: str) -> None:
        self._store.set_setting(key, value)

    # ── Cameras ─────────────────────────────────────────────────────────

    def list_cameras(self) -> list[dict]:
        cams = self._store.list_cameras(_DEFAULT_TENANT)
        conn = self._store.connection()
        try:
            for cam in cams:
                dept_id = cam.get("department_id")
                if dept_id:
                    row = conn.execute(
                        "SELECT name FROM departments WHERE id = ? AND tenant_id = ?",
                        (dept_id, _DEFAULT_TENANT),
                    ).fetchone()
                    cam["department_name"] = row["name"] if row else ""
                else:
                    cam["department_name"] = ""
        finally:
            conn.close()
        return cams

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
        # Try fetching live attendance from running FastAPI backend API first (same endpoint as admin.html)
        try:
            from ui.backend_client import BackendClient
            client = BackendClient(timeout=2.0)
            live_records = client.get_attendance(attendance_date)
            if live_records:
                return live_records
        except Exception:
            pass

        records = self._store.list_attendance(_DEFAULT_TENANT)
        if attendance_date:
            matched = []
            for record in records:
                rec_date = record.get("attendance_date")
                if not rec_date and (record.get("last_appearance") or record.get("first_appearance")):
                    ts = str(record.get("last_appearance") or record.get("first_appearance"))
                    try:
                        from datetime import datetime
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        rec_date = dt.astimezone().strftime("%Y-%m-%d")
                    except Exception:
                        rec_date = ts[:10]
                if rec_date == attendance_date:
                    matched.append(record)
            return matched
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

    def list_alarm_events(self, limit: int = 100) -> list[dict]:
        # Try fetching live unknown face alarms directly from backend API first
        try:
            from ui.backend_client import BackendClient
            client = BackendClient(timeout=2.0)
            live_alarms = client.get_alarms(limit)
            if live_alarms:
                return live_alarms
        except Exception:
            pass
        return self._store.list_alarm_events(limit)

    def clear_sync_events(self) -> None:
        try:
            from ui.backend_client import BackendClient
            client = BackendClient(timeout=2.0)
            client.clear_alarms()
        except Exception:
            pass
        self._store.clear_sync_events()

    def get_reports_stats(self, date_str: str | None = None) -> dict:
        conn = self._store.connection()
        dept_stats = {}
        hour_stats = {}
        known_faces_count = 0
        alarms_count = 0
        try:
            # 1. Attendance count per department
            try:
                dept_rows = conn.execute(
                    "SELECT COALESCE(last_department_name, 'General') as name, COUNT(*) as c FROM attendance_records GROUP BY name"
                ).fetchall()
                dept_stats = {r["name"]: r["c"] for r in dept_rows}
            except Exception:
                pass

            # 2. Hourly check-in activity (general distribution or specific date)
            try:
                if date_str:
                    hour_rows = conn.execute(
                        "SELECT strftime('%H', last_appearance) as hr, COUNT(*) as c FROM attendance_records WHERE attendance_date = ? GROUP BY hr",
                        (date_str,)
                    ).fetchall()
                else:
                    hour_rows = conn.execute(
                        "SELECT strftime('%H', last_appearance) as hr, COUNT(*) as c FROM attendance_records GROUP BY hr"
                    ).fetchall()
                hour_stats = {}
                for r in hour_rows:
                    if r["hr"] is not None:
                        hour_stats[int(r["hr"])] = r["c"]
            except Exception:
                pass

            # 3. Known faces vs Alarms ratio
            try:
                row = conn.execute(
                    "SELECT COALESCE(SUM(appearances), 0) as c FROM attendance_records"
                ).fetchone()
                if row:
                    known_faces_count = row["c"]
            except Exception:
                pass

            # Count of total alarms (from sync_events)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as c FROM sync_events WHERE event_type = 'alarm.triggered'"
                ).fetchone()
                if row:
                    alarms_count = row["c"]
            except Exception:
                pass

            return {
                "department_attendance": dept_stats,
                "hourly_attendance": hour_stats,
                "known_faces_count": known_faces_count,
                "alarms_count": alarms_count,
            }
        finally:
            conn.close()
