"""Optional YOLO weapon detector used as an isolated alert producer."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import cv2

logger = logging.getLogger("weapon_detector")


class WeaponDetector:
    def __init__(self) -> None:
        self.enabled = os.getenv("WEAPON_DETECTION_ENABLED", "false").lower() in {"1", "true", "yes", "on"}
        self.threshold = float(os.getenv("WEAPON_DETECTION_CONFIDENCE", "0.55"))
        self.model_path = Path(os.getenv("WEAPON_DETECTION_MODEL", "models/weapon.pt")).expanduser()
        self.model: Any = None
        self.error: str | None = None
        if self.enabled:
            try:
                from ultralytics import YOLO
                if not self.model_path.exists():
                    raise FileNotFoundError(f"Weapon model not found: {self.model_path}")
                self.model = YOLO(str(self.model_path))
            except Exception as exc:  # optional feature must not break face recognition
                self.error = str(exc)
                logger.warning("Weapon detection disabled: %s", exc)
                self.enabled = False

    def detect(self, image) -> list[dict[str, Any]]:
        if not self.enabled or self.model is None:
            return []
        results = self.model.predict(source=image, conf=self.threshold, verbose=False)
        detections: list[dict[str, Any]] = []
        for result in results:
            names = getattr(result, "names", {}) or {}
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                confidence = float(box.conf[0])
                cls_id = int(box.cls[0])
                coords = [float(value) for value in box.xyxy[0].tolist()]
                detections.append({
                    "label": str(names.get(cls_id, cls_id)),
                    "confidence": confidence,
                    "box": coords,
                })
        return detections

