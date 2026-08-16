"""Recognition Gating Logic for Face Recognition Pipeline.

Determines whether a face track requires model recognition or can reuse cached identity,
slashing CPU workload across multi-camera streams.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from python_recognizer.tracker import TrackedFace

logger = logging.getLogger("python_recognizer.gating")


@dataclass
class GatingConfig:
    """Configurable recognition gating parameters."""

    recognition_cache_ttl_sec: float = 3.0
    motion_shift_ratio: float = 0.15
    min_face_size: int = 16
    match_threshold: float = 0.40
    uncertain_match_min: float = 0.28
    uncertain_match_max: float = 0.50
    max_recognition_jobs_per_sec: int = 60


class RecognitionGater:
    """Evaluates whether recognition is required for a tracked face."""

    def __init__(self, config: Optional[GatingConfig] = None) -> None:
        self.config = config or GatingConfig()
        self._last_job_timestamps: list[float] = []

    def should_recognize(
        self,
        track: TrackedFace,
        camera_role: str = "general",
        force: bool = False,
        telemetry_collector: Optional[Any] = None,
    ) -> bool:
        """Evaluate gating rules for a tracked face."""
        if force:
            return True

        now = time.time()

        # Check rate limit on total recognition jobs / sec
        cutoff = now - 1.0
        self._last_job_timestamps = [t for t in self._last_job_timestamps if t >= cutoff]
        if len(self._last_job_timestamps) >= self.config.max_recognition_jobs_per_sec:
            if telemetry_collector:
                telemetry_collector.record_recognition_avoided()
            return False

        # Rule 1: Entrance / Check-in / Check-out cameras ALWAYS re-confirm faces periodically
        if camera_role in {"check_in", "check_out"}:
            if (now - track.last_recognized_at) >= 2.0:
                self._last_job_timestamps.append(now)
                return True

        # Rule 2: Brand new track (never recognized before)
        if track.identity_label is None and track.last_recognized_at == 0.0:
            self._last_job_timestamps.append(now)
            return True

        # Rule 3: Recognition cache TTL expired
        if (now - track.last_recognized_at) >= self.config.recognition_cache_ttl_sec:
            self._last_job_timestamps.append(now)
            return True

        # Rule 4: Face shifted position significantly
        if track.moved_significantly(self.config.motion_shift_ratio):
            self._last_job_timestamps.append(now)
            return True

        # Rule 5: Previous match was low-confidence or borderline uncertain
        if track.identity_label is not None:
            if track.identity_confidence < self.config.match_threshold or (
                self.config.uncertain_match_min <= track.identity_confidence <= self.config.uncertain_match_max
            ):
                self._last_job_timestamps.append(now)
                return True

        # Gated! Avoid recognition call and reuse cached identity
        if telemetry_collector:
            telemetry_collector.record_recognition_avoided()

        return False
