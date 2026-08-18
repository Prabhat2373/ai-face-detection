"""Central Pipeline Scheduler for Scalable Multi-Camera Face Recognition.

Integrates Latest-Frame Buffering, Shared Detector & Recognizer Engines, Per-Camera CPU Trackers,
Priority Crop Batching, Recognition Gating, and Adaptive Resource Governance.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from python_recognizer.batcher import PriorityCropJob, PriorityRecognitionQueue, compute_crop_priority
from python_recognizer.gating import GatingConfig, RecognitionGater
from python_recognizer.governance import ResourceGovernor, ResourceLimits
from python_recognizer.runtime import ModelEngineManager
from python_recognizer.telemetry import TelemetryCollector, telemetry_collector
from python_recognizer.tracker import CentroidIOUTracker, TrackedFace

logger = logging.getLogger("python_recognizer.scheduler")


class LatestFrameBuffer:
    """Thread-safe latest-frame storage dropping stale frames for all cameras."""

    def __init__(self) -> None:
        self._frames: Dict[str, Tuple[np.ndarray, float]] = {}
        self._lock = threading.Lock()

    def push(self, camera_id: str, frame: np.ndarray) -> None:
        now = time.monotonic()
        with self._lock:
            self._frames[camera_id] = (frame, now)

    def pop_latest(self, camera_id: str) -> Optional[Tuple[np.ndarray, float]]:
        with self._lock:
            return self._frames.pop(camera_id, None)

    def peek_latest(self, camera_id: str) -> Optional[Tuple[np.ndarray, float]]:
        with self._lock:
            return self._frames.get(camera_id)

    def active_cameras(self) -> List[str]:
        with self._lock:
            return list(self._frames.keys())


class CentralInferenceScheduler:
    """Central inference scheduler managing multi-camera detection, tracking, gating, and batching."""

    def __init__(
        self,
        engine_manager: ModelEngineManager,
        gallery_provider: Callable[[], List[Dict[str, Any]]],
        event_callback: Optional[Callable[[str, str, List[Dict[str, Any]], np.ndarray], None]] = None,
        telemetry: Optional[TelemetryCollector] = None,
    ) -> None:
        self.engine_manager = engine_manager
        self.gallery_provider = gallery_provider
        self.event_callback = event_callback
        self.telemetry = telemetry or telemetry_collector

        self.frame_buffer = LatestFrameBuffer()
        self.governor = ResourceGovernor()
        self.gater = RecognitionGater()
        self.rec_queue = PriorityRecognitionQueue(batch_size=8, max_wait_ms=15.0)
        
        self.trackers: Dict[str, CentroidIOUTracker] = {}
        self._trackers_lock = threading.Lock()

        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._batch_worker_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.governor.start()
        
        self._scheduler_thread = threading.Thread(target=self._detection_loop, daemon=True)
        self._scheduler_thread.start()

        self._batch_worker_thread = threading.Thread(target=self._recognition_batch_loop, daemon=True)
        self._batch_worker_thread.start()
        
        logger.info("CentralInferenceScheduler started successfully.")

    def stop(self) -> None:
        self._running = False
        self.governor.stop()
        logger.info("CentralInferenceScheduler stopped.")

    def push_frame(self, camera_id: str, frame: np.ndarray) -> None:
        self.frame_buffer.push(camera_id, frame)
        self.telemetry.record_frame_received()

    def _get_tracker(self, camera_id: str) -> CentroidIOUTracker:
        with self._trackers_lock:
            if camera_id not in self.trackers:
                self.trackers[camera_id] = CentroidIOUTracker(camera_id=camera_id)
            return self.trackers[camera_id]

    def _detection_loop(self) -> None:
        """Main detection loop processing newest frames from active cameras."""
        while self._running:
            active_cams = self.frame_buffer.active_cameras()
            if not active_cams:
                time.sleep(0.01)
                continue

            for camera_id in active_cams:
                if not self._running:
                    break
                item = self.frame_buffer.pop_latest(camera_id)
                if item is None:
                    continue

                frame, timestamp = item
                start_det = time.monotonic()
                
                # Use governor settings for image scale and detector stride
                max_dim = self.governor.detection_max_dim
                
                # Execute face detection via shared detector engine
                raw_faces = self.engine_manager.detect_faces(frame, max_dim=max_dim)
                det_latency_ms = (time.monotonic() - start_det) * 1000.0
                self.telemetry.record_detection(det_latency_ms, len(raw_faces))

                # Extract bounding boxes for tracker
                detections = []
                for face in raw_faces:
                    bbox = [float(v) for v in getattr(face, "bbox", [0, 0, 0, 0])]
                    conf = float(getattr(face, "det_score", getattr(face, "score", 0.85)))
                    detections.append({"bbox": bbox, "confidence": conf, "raw": face})

                # Update per-camera face tracker
                tracker = self._get_tracker(camera_id)
                active_tracks = tracker.update(detections, telemetry_collector=self.telemetry)

                # Process tracks through recognition gating & priority queue
                gallery = self.gallery_provider()
                camera_role = "general"  # Default role
                
                processed_faces_serialized: List[Dict[str, Any]] = []

                for track in active_tracks:
                    # Check if recognition is required
                    if self.gater.should_recognize(track, camera_role=camera_role, telemetry_collector=self.telemetry):
                        # Crop face image for recognition
                        x1, y1, x2, y2 = [int(v) for v in track.bbox]
                        h_f, w_f = frame.shape[:2]
                        x1, y1 = max(0, x1), max(0, y1)
                        x2, y2 = min(w_f, x2), min(h_f, y2)
                        
                        if (x2 - x1) >= 16 and (y2 - y1) >= 16:
                            crop = frame[y1:y2, x1:x2].copy()
                            priority = compute_crop_priority(track, camera_role)
                            
                            job = PriorityCropJob(
                                priority=priority,
                                timestamp=time.time(),
                                camera_id=camera_id,
                                camera_role=camera_role,
                                track=track,
                                face_crop=crop,
                            )
                            self.rec_queue.enqueue(job, telemetry_collector=self.telemetry)

                    # Prepare face payload for UI preview / event dispatch
                    serialized_face = {
                        "trackId": track.track_id,
                        "trackStatus": track.track_status,
                        "isProcessable": track.is_processable,
                        "qualityScore": track.quality_score,
                        "bbox": [float(v) for v in track.bbox],
                        "confidence": float(track.detection_confidence),
                        "isUnknown": track.is_unknown,
                        "match": {
                            "label": track.identity_label,
                            "confidence": float(track.identity_confidence),
                            "employeeCode": track.employee_code,
                        } if track.track_status == "known" else None,
                    }
                    processed_faces_serialized.append(serialized_face)

                if self.event_callback:
                    try:
                        self.event_callback(camera_id, camera_role, processed_faces_serialized, frame)
                    except Exception as exc:
                        logger.warning("Event callback error for camera %s: %s", camera_id, exc)

            time.sleep(0.005)

    def _recognition_batch_loop(self) -> None:
        """Background recognition worker loop processing priority micro-batches."""
        while self._running:
            batch = self.rec_queue.get_batch(timeout_sec=0.05)
            if not batch:
                continue

            gallery = self.gallery_provider()

            for job in batch:
                if not self._running:
                    break
                start_rec = time.monotonic()

                # Quality assessment
                from python_recognizer.tracker import evaluate_face_quality
                is_processable, q_score, reason = evaluate_face_quality(
                    job.face_crop, det_conf=job.track.detection_confidence
                )
                
                # Extract embedding via custom student model
                emb = self.engine_manager.extract_embedding(job.face_crop, use_teacher=False)
                
                if emb is not None and gallery:
                    match_rec, score, _ = self.engine_manager.match_against_gallery(
                        embedding=emb,
                        gallery=gallery,
                        match_threshold=0.52,
                        telemetry_collector=self.telemetry,
                    )
                    
                    if match_rec:
                        job.track.set_identity(
                            label=match_rec.get("label"),
                            confidence=score,
                            employee_code=match_rec.get("employee_code"),
                            match_data=match_rec,
                            is_processable=is_processable,
                            quality_score=q_score,
                        )
                    else:
                        job.track.set_identity(
                            label=None,
                            confidence=score,
                            is_processable=is_processable,
                            quality_score=q_score,
                        )
                else:
                    job.track.set_identity(
                        label=None,
                        confidence=0.0,
                        is_processable=is_processable,
                        quality_score=q_score,
                    )

                rec_latency_ms = (time.monotonic() - start_rec) * 1000.0
                self.telemetry.record_recognition(rec_latency_ms, 1, is_teacher=False)

            time.sleep(0.002)
