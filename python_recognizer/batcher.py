"""Multi-Camera Priority Recognition Queue & Batcher.

Collects face crops across multiple cameras and batches them by priority
to maximize GPU/CPU vectorization efficiency.
"""

from __future__ import annotations

import heapq
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from python_recognizer.tracker import TrackedFace

logger = logging.getLogger("python_recognizer.batcher")


@dataclass(order=True)
class PriorityCropJob:
    """Recognition job item sorted by priority (lower number = higher priority)."""

    priority: int
    timestamp: float
    camera_id: str = field(compare=False)
    camera_role: str = field(compare=False)
    track: TrackedFace = field(compare=False)
    face_crop: np.ndarray = field(compare=False)
    callback: Optional[Callable[[Optional[Dict[str, Any]], float, bool], None]] = field(default=None, compare=False)


def compute_crop_priority(track: TrackedFace, camera_role: str) -> int:
    """Compute priority rank (1 = Highest, 6 = Lowest).
    
    Priority Order:
    1. New faces (unrecognized)
    2. Unknown faces needing confirmation
    3. Low-confidence matches
    4. Entrance/check-in/check-out cameras
    5. Moving faces
    6. Stable known faces
    """
    if track.identity_label is None and track.last_recognized_at == 0.0:
        return 1
    if track.is_unknown:
        return 2
    if track.identity_confidence < 0.45:
        return 3
    if camera_role in {"check_in", "check_out"}:
        return 4
    if track.moved_significantly(0.15):
        return 5
    return 6


class PriorityRecognitionQueue:
    """Thread-safe priority recognition job queue supporting micro-batching."""

    def __init__(
        self,
        batch_size: int = 8,
        max_wait_ms: float = 15.0,
        max_queue_depth: int = 200,
    ) -> None:
        self.batch_size = max(1, batch_size)
        self.max_wait_sec = max_wait_ms / 1000.0
        self.max_queue_depth = max_queue_depth
        
        self._heap: List[PriorityCropJob] = []
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._dropped_count = 0

    def enqueue(self, job: PriorityCropJob, telemetry_collector: Optional[Any] = None) -> bool:
        with self._lock:
            if len(self._heap) >= self.max_queue_depth:
                # Drop lowest priority item if queue is full
                heapq.heappop(self._heap)
                self._dropped_count += 1
                if telemetry_collector:
                    telemetry_collector.record_frame_dropped()

            heapq.heappush(self._heap, job)
            if telemetry_collector:
                telemetry_collector.set_queue_depth(len(self._heap))
            self._not_empty.notify()
            return True

    def get_batch(self, timeout_sec: Optional[float] = None) -> List[PriorityCropJob]:
        """Collect up to batch_size jobs within max_wait_sec."""
        batch: List[PriorityCropJob] = []
        start_time = time.monotonic()

        with self._lock:
            while not self._heap:
                rem = (timeout_sec if timeout_sec is not None else self.max_wait_sec) - (time.monotonic() - start_time)
                if rem <= 0:
                    return []
                self._not_empty.wait(timeout=rem)

            # Pull up to batch_size items from priority heap
            while self._heap and len(batch) < self.batch_size:
                batch.append(heapq.heappop(self._heap))

        return batch

    def size(self) -> int:
        with self._lock:
            return len(self._heap)
