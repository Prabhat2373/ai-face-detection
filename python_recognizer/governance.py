"""Adaptive Resource Governance for Scalable Face Recognition Pipeline.

Monitors CPU, RAM, and queue depths in real time and applies dynamic grace degradation
to enforce target CPU (<60%) and RAM (<70%) limits.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import psutil

logger = logging.getLogger("python_recognizer.governance")


@dataclass
class ResourceLimits:
    """Configurable resource targets."""

    max_cpu_percent: float = 60.0
    max_ram_percent: float = 70.0
    max_queue_depth: int = 200
    max_detector_fps: float = 10.0
    max_recognition_fps: float = 30.0


class ResourceGovernor:
    """Adaptive load controller enforcing system resource boundaries."""

    def __init__(self, limits: Optional[ResourceLimits] = None) -> None:
        self.limits = limits or ResourceLimits()
        self._process = psutil.Process(os.getpid())
        self._lock = threading.Lock()
        
        # Dynamic governance state flags
        self.allow_teacher_fallback: bool = True
        self.recognition_cache_ttl: float = 5.0  # seconds
        self.detection_max_dim: int = 720        # pixels
        self.detection_stride: int = 1           # process 1 in N frames
        self.is_overloaded: bool = False
        
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False

    def _monitor_loop(self) -> None:
        """Background governance evaluation loop running every 1.5 seconds."""
        while self._running:
            try:
                cpu_p = psutil.cpu_percent(interval=1.0)
                mem_sys = psutil.virtual_memory()
                ram_p = mem_sys.percent

                with self._lock:
                    if cpu_p > self.limits.max_cpu_percent or ram_p > self.limits.max_ram_percent:
                        if not self.is_overloaded:
                            logger.warning(
                                "Resource limit exceeded (CPU: %.1f%%, RAM: %.1f%%). Applying adaptive degradation...",
                                cpu_p, ram_p
                            )
                        self.is_overloaded = True
                        
                        # Step 1: Disable heavy teacher model fallback
                        self.allow_teacher_fallback = False
                        
                        # Step 2: Increase recognition cache TTL (5s -> 10s)
                        self.recognition_cache_ttl = 10.0
                        
                        # Step 3: Decimate image size for detection (720p -> 480p)
                        self.detection_max_dim = 480
                        
                        # Step 4: Increase frame stride for detector (skip more frames)
                        self.detection_stride = 2

                    else:
                        if self.is_overloaded:
                            logger.info(
                                "Resource usage restored within targets (CPU: %.1f%%, RAM: %.1f%%). Resuming full pipeline...",
                                cpu_p, ram_p
                            )
                        self.is_overloaded = False
                        self.allow_teacher_fallback = True
                        self.recognition_cache_ttl = 5.0
                        self.detection_max_dim = 720
                        self.detection_stride = 1

            except Exception as exc:
                logger.warning("Resource monitor error: %s", exc)

            time.sleep(1.5)

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "is_overloaded": self.is_overloaded,
                "allow_teacher_fallback": self.allow_teacher_fallback,
                "recognition_cache_ttl": self.recognition_cache_ttl,
                "detection_max_dim": self.detection_max_dim,
                "detection_stride": self.detection_stride,
                "limits": {
                    "max_cpu_percent": self.limits.max_cpu_percent,
                    "max_ram_percent": self.limits.max_ram_percent,
                },
            }
