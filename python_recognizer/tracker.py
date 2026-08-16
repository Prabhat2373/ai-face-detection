"""CPU-Efficient Face Tracker for Scalable Face Recognition Pipeline.

Implements bounding-box overlap (IOU), centroid tracking, and track state management
to track faces between detector calls, avoiding repetitive model inference.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("python_recognizer.tracker")


def compute_iou(boxA: List[float], boxB: List[float]) -> float:
    """Compute Intersection over Union (IOU) between two bounding boxes [x1, y1, x2, y2]."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    interArea = max(0.0, xB - xA) * max(0.0, yB - yA)
    boxAArea = max(0.0, boxA[2] - boxA[0]) * max(0.0, boxA[3] - boxA[1])
    boxBArea = max(0.0, boxB[2] - boxB[0]) * max(0.0, boxB[3] - boxB[1])

    denominator = boxAArea + boxBArea - interArea
    if denominator <= 0:
        return 0.0
    return float(interArea / denominator)


def compute_centroid(bbox: List[float]) -> Tuple[float, float]:
    """Compute centroid (cx, cy) of bounding box [x1, y1, x2, y2]."""
    return ((bbox[0] + bbox[2]) / 2.0, (bbox[1] + bbox[3]) / 2.0)


def evaluate_face_quality(crop: Optional[np.ndarray], det_conf: float = 1.0) -> Tuple[bool, float, str]:
    """Evaluates whether a face crop is clear and processable for recognition.
    
    Returns (is_processable: bool, quality_score: float, reason: str).
    """
    if crop is None or crop.size == 0:
        return False, 0.0, "empty_crop"

    h, w = crop.shape[:2]
    if min(h, w) < 20:
        return False, 0.2, "low_resolution"

    try:
        import cv2
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if len(crop.shape) == 3 else crop

        # 1. Blur assessment using Laplacian variance
        lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if lap_var < 35.0:
            return False, 0.3, "heavy_blur"

        # 2. Contrast / illumination assessment
        std_dev = float(np.std(gray))
        if std_dev < 12.0:
            return False, 0.3, "low_contrast"

        res_score = min(1.0, min(h, w) / 80.0)
        blur_score = min(1.0, lap_var / 120.0)
        contrast_score = min(1.0, std_dev / 45.0)

        quality_score = round(0.4 * res_score + 0.4 * blur_score + 0.2 * contrast_score, 2)
        return True, quality_score, "ok"
    except Exception:
        return True, 0.5, "ok"


@dataclass
class TrackedFace:
    """State representation of a tracked face across frames."""

    track_id: str
    camera_id: str
    bbox: List[float]  # [x1, y1, x2, y2]
    centroid: Tuple[float, float]
    detection_confidence: float
    created_at: float = field(default_factory=time.time)
    last_updated_at: float = field(default_factory=time.time)

    # Motion tracking
    vx: float = 0.0
    vy: float = 0.0
    frames_since_detection: int = 0
    tracker_confidence: float = 1.0  # Decays when unobserved by detector

    # Identity & 3-State Tracking ("tracking", "known", "unknown")
    track_status: str = "tracking"  # "tracking" | "known" | "unknown"
    is_processable: bool = False
    quality_score: float = 0.0
    identity_label: Optional[str] = None
    identity_confidence: float = 0.0
    employee_code: Optional[str] = None
    last_recognized_at: float = 0.0
    last_recognized_bbox: Optional[List[float]] = None
    is_unknown: bool = False  # Only True when track_status == "unknown" (confirmed processable unknown)
    match_data: Optional[Dict[str, Any]] = None

    @property
    def width(self) -> float:
        return max(0.0, self.bbox[2] - self.bbox[0])

    @property
    def height(self) -> float:
        return max(0.0, self.bbox[3] - self.bbox[1])

    @property
    def area(self) -> float:
        return self.width * self.height

    def update_position(self, new_bbox: List[float], new_det_conf: float) -> None:
        now = time.time()
        dt = max(0.001, now - self.last_updated_at)
        new_cx, new_cy = compute_centroid(new_bbox)

        # Estimate velocity
        self.vx = (new_cx - self.centroid[0]) / dt
        self.vy = (new_cy - self.centroid[1]) / dt

        self.bbox = new_bbox
        self.centroid = (new_cx, new_cy)
        self.detection_confidence = new_det_conf
        self.last_updated_at = now
        self.frames_since_detection = 0
        self.tracker_confidence = min(1.0, self.tracker_confidence + 0.2)

    def predict_next_position(self, dt: float = 0.033) -> List[float]:
        """Predict bounding box based on velocity during detector skipped frames."""
        dx = self.vx * dt
        dy = self.vy * dt
        return [
            self.bbox[0] + dx,
            self.bbox[1] + dy,
            self.bbox[2] + dx,
            self.bbox[3] + dy,
        ]

    def decay_confidence(self) -> None:
        """Decay tracker confidence when detector skips this track."""
        self.frames_since_detection += 1
        self.tracker_confidence *= 0.50

    def set_identity(
        self,
        label: Optional[str],
        confidence: float,
        employee_code: Optional[str] = None,
        match_data: Optional[Dict[str, Any]] = None,
        is_processable: bool = True,
        quality_score: float = 0.5,
    ) -> None:
        self.is_processable = is_processable
        self.quality_score = quality_score
        self.last_recognized_at = time.time()
        self.last_recognized_bbox = list(self.bbox)
        self.match_data = match_data

        if label is not None:
            # Recognized registered employee
            self.track_status = "known"
            self.identity_label = label
            self.identity_confidence = confidence
            self.employee_code = employee_code
            self.is_unknown = False
        else:
            # Unmatched candidate
            # If face is low quality / unprocessable or new observation frame, keep status as "tracking" (neutral)
            if not is_processable or confidence < 0.25:
                self.track_status = "tracking"
                self.identity_label = "Tracking..."
                self.identity_confidence = confidence
                self.employee_code = None
                self.is_unknown = False  # Do NOT trigger false unknown alarms on blurry/unprocessable crops!
            else:
                # Confirmed processable face that is genuinely unknown
                self.track_status = "unknown"
                self.identity_label = "Unknown"
                self.identity_confidence = confidence
                self.employee_code = None
                self.is_unknown = True

    def moved_significantly(self, threshold_ratio: float = 0.20) -> bool:
        """Check if face bounding box has moved significantly since last recognition."""
        if not self.last_recognized_bbox:
            return True
        prev_cx, prev_cy = compute_centroid(self.last_recognized_bbox)
        curr_cx, curr_cy = self.centroid
        dist = math.hypot(curr_cx - prev_cx, curr_cy - prev_cy)
        diag = math.hypot(self.width, self.height)
        if diag <= 0:
            return True
        return (dist / diag) > threshold_ratio


# ---------------------------------------------------------------------------
# Centroid & IOU Tracker
# ---------------------------------------------------------------------------

class CentroidIOUTracker:
    """CPU-efficient face tracker maintaining tracks per camera."""

    def __init__(
        self,
        camera_id: str,
        max_idle_seconds: float = 3.0,
        iou_threshold: float = 0.30,
        dist_threshold_ratio: float = 0.80,
    ) -> None:
        self.camera_id = camera_id
        self.max_idle_seconds = max_idle_seconds
        self.iou_threshold = iou_threshold
        self.dist_threshold_ratio = dist_threshold_ratio
        
        self.tracks: Dict[str, TrackedFace] = {}
        self._next_track_num = 1

    def _generate_track_id(self) -> str:
        tid = f"{self.camera_id}_tr_{self._next_track_num:05d}"
        self._next_track_num += 1
        return tid

    def update(
        self,
        detections: List[Dict[str, Any]],
        telemetry_collector: Optional[Any] = None,
    ) -> List[TrackedFace]:
        """Update tracks with new face detections.
        
        detections: list of dicts with keys 'bbox' [x1,y1,x2,y2], 'confidence' float, etc.
        """
        now = time.time()

        # Step 1: Predict positions for existing tracks
        for track in self.tracks.values():
            dt = max(0.001, now - track.last_updated_at)
            track.bbox = track.predict_next_position(dt)
            track.centroid = compute_centroid(track.bbox)

        active_tracks = list(self.tracks.values())
        unmatched_detections = list(range(len(detections)))
        matched_tracks: List[TrackedFace] = []

        if active_tracks and detections:
            # Build cost matrix using 1.0 - IOU
            cost_matrix = np.ones((len(active_tracks), len(detections)), dtype=np.float32)
            for i, trk in enumerate(active_tracks):
                for j, det in enumerate(detections):
                    det_box = [float(v) for v in det.get("bbox", [0, 0, 0, 0])]
                    iou = compute_iou(trk.bbox, det_box)
                    cost_matrix[i, j] = 1.0 - iou

            # Greedy assignment by minimum cost (maximum IOU)
            matched_indices: List[Tuple[int, int]] = []
            while True:
                min_val = float(np.min(cost_matrix))
                if min_val > (1.0 - self.iou_threshold):
                    break
                row, col = np.unravel_index(np.argmin(cost_matrix), cost_matrix.shape)
                matched_indices.append((row, col))
                cost_matrix[row, :] = 1.0
                cost_matrix[:, col] = 1.0

            # Update matched tracks
            matched_det_set = set()
            for r_idx, c_idx in matched_indices:
                trk = active_tracks[r_idx]
                det = detections[c_idx]
                det_box = [float(v) for v in det.get("bbox", [0, 0, 0, 0])]
                det_conf = float(det.get("confidence", 0.0))
                trk.update_position(det_box, det_conf)
                matched_tracks.append(trk)
                matched_det_set.add(c_idx)

            unmatched_detections = [j for j in range(len(detections)) if j not in matched_det_set]

        # Step 2: Create new tracks for unmatched detections
        for j in unmatched_detections:
            det = detections[j]
            det_box = [float(v) for v in det.get("bbox", [0, 0, 0, 0])]
            det_conf = float(det.get("confidence", 0.0))
            
            # Check minimum face size
            w = max(0, det_box[2] - det_box[0])
            h = max(0, det_box[3] - det_box[1])
            if min(w, h) < 16:
                continue

            track_id = self._generate_track_id()
            trk = TrackedFace(
                track_id=track_id,
                camera_id=self.camera_id,
                bbox=det_box,
                centroid=compute_centroid(det_box),
                detection_confidence=det_conf,
            )
            self.tracks[track_id] = trk
            matched_tracks.append(trk)
            if telemetry_collector:
                telemetry_collector.record_track_created()

        # Step 3: Decay confidence of unobserved tracks
        matched_ids = {trk.track_id for trk in matched_tracks}
        for track in list(self.tracks.values()):
            if track.track_id not in matched_ids:
                track.decay_confidence()

        # Step 4: Expire inactive tracks
        self.expire_tracks(telemetry_collector)

        if telemetry_collector:
            telemetry_collector.set_active_tracks(len(self.tracks))

        return list(self.tracks.values())

    def expire_tracks(self, telemetry_collector: Optional[Any] = None) -> None:
        """Purge tracks that have been lost for longer than max_idle_seconds."""
        now = time.time()
        to_delete = []
        for tid, trk in self.tracks.items():
            idle_time = now - trk.last_updated_at
            if idle_time > self.max_idle_seconds or trk.tracker_confidence < 0.1:
                to_delete.append(tid)

        for tid in to_delete:
            del self.tracks[tid]
            if telemetry_collector:
                telemetry_collector.record_track_expired()

    def get_active_tracks(self) -> List[TrackedFace]:
        return list(self.tracks.values())
