"""Small HTTP client for the local Python recognizer backend."""

from __future__ import annotations

import json
import os
from urllib import error as urllib_error
from urllib import parse, request


DEFAULT_BACKEND_URL = os.getenv("FACEAGENT_BACKEND_URL", "http://127.0.0.1:5055").rstrip("/")


class BackendClient:
    """Blocking client used from Qt timers and button handlers."""

    def __init__(self, base_url: str = DEFAULT_BACKEND_URL, timeout: float = 2.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def health(self) -> dict:
        return self._json("GET", "/health")

    def status(self) -> dict:
        return self._json("GET", "/status")

    def start(self, camera_id: str | None = None, camera_role: str | None = None) -> dict:
        payload: dict[str, str] = {}
        if camera_id:
            payload["cameraId"] = camera_id
        if camera_role:
            payload["cameraRole"] = camera_role
        return self._json("POST", "/start", payload)

    def stop(self) -> dict:
        return self._json("POST", "/stop", {})

    def get_attendance(self, date: str | None = None) -> list[dict]:
        """Fetch attendance records directly from backend API (same endpoint used by admin.html)."""
        try:
            path = f"/attendance?date={date}" if date else "/attendance"
            res = self._json("GET", path)
            if isinstance(res, dict) and "attendance" in res:
                return res["attendance"]
            if isinstance(res, list):
                return res
            return []
        except Exception:
            return []

    def save_employee(self, payload: dict) -> dict:
        """Create or update an employee on the backend API."""
        emp_id = payload.get("id")
        if emp_id:
            encoded_id = parse.quote(str(emp_id), safe="")
            return self._json("PUT", f"/employees/{encoded_id}", payload)
        return self._json("POST", "/employees", payload)

    def upload_employee_photos(self, employee_id: str, photos_b64: list[str], timeout: float = 60.0) -> dict:
        """Upload employee photos and register their face embeddings.

        The trailing-slash retry keeps this compatible with backend instances
        configured to redirect or expose the slash-normalized route.
        """
        encoded_id = parse.quote(employee_id, safe="")
        payload = {"photos": photos_b64}
        try:
            return self._json("POST", f"/employees/{encoded_id}/photos", payload, timeout=timeout)
        except urllib_error.HTTPError as exc:
            if exc.code != 404:
                raise
            return self._json("POST", f"/employees/{encoded_id}/photos/", payload, timeout=timeout)

    def frame(self, camera_id: str | None = None, camera_role: str | None = None) -> bytes | None:
        query = {}
        if camera_id:
            query["cameraId"] = camera_id
        if camera_role:
            query["cameraRole"] = camera_role
        suffix = f"?{parse.urlencode(query)}" if query else ""
        try:
            with request.urlopen(f"{self.base_url}/frame.jpg{suffix}", timeout=self.timeout) as response:
                return response.read()
        except (urllib_error.URLError, TimeoutError):
            return None

    def _json(self, method: str, path: str, payload: dict | None = None, timeout: float | None = None) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        req_timeout = timeout if timeout is not None else self.timeout
        try:
            with request.urlopen(req, timeout=req_timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8")
                err_json = json.loads(body)
                detail = err_json.get("detail") or err_json.get("message")
                if detail:
                    raise RuntimeError(detail) from exc
            except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
                pass
            raise
