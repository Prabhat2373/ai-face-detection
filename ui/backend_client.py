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

    def _json(self, method: str, path: str, payload: dict | None = None) -> dict:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))
