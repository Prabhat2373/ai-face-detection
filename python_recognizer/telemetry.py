"""Telemetry and Benchmark System for Scalable Face Recognition Pipeline.

Provides system metrics collection (CPU, RAM, GPU, VRAM, latencies, FPS, queues, tracks)
and a benchmark runner supporting 1 to 100 camera synthetic or video workloads.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np
import psutil

logger = logging.getLogger("python_recognizer.telemetry")


# ---------------------------------------------------------------------------
# GPU & Hardware Monitoring Helpers
# ---------------------------------------------------------------------------

def get_gpu_metrics() -> Dict[str, Any]:
    """Retrieve GPU and VRAM metrics if CUDA/NVML or PyTorch GPU is available."""
    gpu_info: Dict[str, Any] = {
        "available": False,
        "name": None,
        "gpu_percent": 0.0,
        "vram_used_mb": 0.0,
        "vram_total_mb": 0.0,
        "vram_percent": 0.0,
        "provider": "CPUExecutionProvider",
    }
    
    # Try pynvml / nvidia-ml-py first
    try:
        import pynvml
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        if device_count > 0:
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            name = pynvml.nvmlDeviceGetName(handle)
            if isinstance(name, bytes):
                name = name.decode("utf-8")
            util = pynvml.nvmlDeviceGetUtilizationRates(handle)
            mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
            gpu_info.update({
                "available": True,
                "name": name,
                "gpu_percent": float(util.gpu),
                "vram_used_mb": float(mem.used / (1024 * 1024)),
                "vram_total_mb": float(mem.total / (1024 * 1024)),
                "vram_percent": float(mem.used / mem.total * 100.0) if mem.total > 0 else 0.0,
                "provider": "CUDAExecutionProvider",
            })
            return gpu_info
    except Exception:
        pass

    # Try PyTorch as fallback for GPU info
    try:
        import torch
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            mem_allocated = torch.cuda.memory_allocated(0) / (1024 * 1024)
            mem_reserved = torch.cuda.memory_reserved(0) / (1024 * 1024)
            gpu_info.update({
                "available": True,
                "name": device_name,
                "gpu_percent": 0.0,  # Torch doesn't report core utilization easily
                "vram_used_mb": float(mem_allocated),
                "vram_total_mb": float(mem_reserved),
                "vram_percent": float(mem_allocated / mem_reserved * 100.0) if mem_reserved > 0 else 0.0,
                "provider": "CUDAExecutionProvider",
            })
            return gpu_info
    except Exception:
        pass

    return gpu_info


# ---------------------------------------------------------------------------
# Telemetry Metrics Aggregator
# ---------------------------------------------------------------------------

class TelemetryCollector:
    """Thread-safe telemetry metrics collector."""

    def __init__(self, history_window_sec: float = 10.0) -> None:
        self.history_window_sec = history_window_sec
        self._lock = threading.Lock()
        self._process = psutil.Process(os.getpid())
        
        # Counters
        self.total_frames_received = 0
        self.total_frames_dropped = 0
        self.total_detections = 0
        self.total_recognitions = 0
        self.total_teacher_inferences = 0
        self.total_student_inferences = 0
        self.total_tracks_created = 0
        self.total_tracks_expired = 0
        self.recognition_calls_avoided = 0
        
        # Current Gauges
        self.active_camera_count = 0
        self.current_queue_depth = 0
        self.current_active_tracks = 0
        self.active_provider = "CPUExecutionProvider"
        
        # Rolling timestamp logs for FPS & Latency calculation: (timestamp, value)
        self._detection_timestamps: List[float] = []
        self._detection_latencies: List[float] = []
        self._recognition_timestamps: List[float] = []
        self._recognition_latencies: List[float] = []
        
    def set_camera_count(self, count: int) -> None:
        with self._lock:
            self.active_camera_count = count

    def set_active_provider(self, provider: str) -> None:
        with self._lock:
            self.active_provider = provider

    def set_queue_depth(self, depth: int) -> None:
        with self._lock:
            self.current_queue_depth = depth

    def set_active_tracks(self, count: int) -> None:
        with self._lock:
            self.current_active_tracks = count

    def record_frame_received(self, count: int = 1) -> None:
        with self._lock:
            self.total_frames_received += count

    def record_frame_dropped(self, count: int = 1) -> None:
        with self._lock:
            self.total_frames_dropped += count

    def record_detection(self, latency_ms: float, faces_found: int = 0) -> None:
        now = time.monotonic()
        with self._lock:
            self.total_detections += 1
            self._detection_timestamps.append(now)
            self._detection_latencies.append(latency_ms)
            self._prune_history(now)

    def record_recognition(self, latency_ms: float, faces_count: int = 1, is_teacher: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            self.total_recognitions += faces_count
            if is_teacher:
                self.total_teacher_inferences += faces_count
            else:
                self.total_student_inferences += faces_count
            self._recognition_timestamps.append(now)
            self._recognition_latencies.append(latency_ms)
            self._prune_history(now)

    def record_recognition_avoided(self, count: int = 1) -> None:
        with self._lock:
            self.recognition_calls_avoided += count

    def record_track_created(self, count: int = 1) -> None:
        with self._lock:
            self.total_tracks_created += count

    def record_track_expired(self, count: int = 1) -> None:
        with self._lock:
            self.total_tracks_expired += count

    def _prune_history(self, now: float) -> None:
        cutoff = now - self.history_window_sec
        
        while self._detection_timestamps and self._detection_timestamps[0] < cutoff:
            self._detection_timestamps.pop(0)
            self._detection_latencies.pop(0)
            
        while self._recognition_timestamps and self._recognition_timestamps[0] < cutoff:
            self._recognition_timestamps.pop(0)
            self._recognition_latencies.pop(0)

    def get_metrics(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            self._prune_history(now)
            
            # System metrics
            cpu_percent = psutil.cpu_percent(interval=None)
            mem_info = self._process.memory_info()
            sys_mem = psutil.virtual_memory()
            gpu_metrics = get_gpu_metrics()

            # Detection FPS & Latency
            det_count = len(self._detection_timestamps)
            det_fps = det_count / self.history_window_sec if self.history_window_sec > 0 else 0.0
            avg_det_lat = (sum(self._detection_latencies) / det_count) if det_count > 0 else 0.0

            # Recognition FPS & Latency
            rec_count = len(self._recognition_timestamps)
            rec_fps = rec_count / self.history_window_sec if self.history_window_sec > 0 else 0.0
            avg_rec_lat = (sum(self._recognition_latencies) / rec_count) if rec_count > 0 else 0.0

            return {
                "timestamp": time.time(),
                "system": {
                    "cpu_percent": cpu_percent,
                    "ram_process_mb": round(mem_info.rss / (1024 * 1024), 2),
                    "ram_system_used_mb": round((sys_mem.total - sys_mem.available) / (1024 * 1024), 2),
                    "ram_system_total_mb": round(sys_mem.total / (1024 * 1024), 2),
                    "ram_system_percent": sys_mem.percent,
                    "gpu": gpu_metrics,
                },
                "pipeline": {
                    "active_camera_count": self.active_camera_count,
                    "active_provider": self.active_provider,
                    "detection_fps": round(det_fps, 2),
                    "detection_latency_ms": round(avg_det_lat, 2),
                    "recognition_fps": round(rec_fps, 2),
                    "recognition_latency_ms": round(avg_rec_lat, 2),
                    "queue_depth": self.current_queue_depth,
                    "dropped_frames": self.total_frames_dropped,
                    "received_frames": self.total_frames_received,
                    "active_tracks": self.current_active_tracks,
                    "tracks_created": self.total_tracks_created,
                    "tracks_expired": self.total_tracks_expired,
                    "recognition_calls_avoided": self.recognition_calls_avoided,
                    "full_model_inferences": {
                        "total": self.total_teacher_inferences + self.total_student_inferences,
                        "teacher_buffalo_l": self.total_teacher_inferences,
                        "student_lightweight": self.total_student_inferences,
                    },
                },
            }


# Global telemetry singleton instance
telemetry_collector = TelemetryCollector()


# ---------------------------------------------------------------------------
# Synthetic Frame & Video Camera Workload Generators
# ---------------------------------------------------------------------------

class SyntheticCameraStream:
    """Generates synthetic camera frames or replays a local video file for benchmark testing."""

    def __init__(
        self,
        camera_id: str,
        fps: float = 15.0,
        width: int = 640,
        height: int = 480,
        video_path: Optional[str] = None,
        draw_synthetic_faces: bool = True,
    ) -> None:
        self.camera_id = camera_id
        self.fps = fps
        self.width = width
        self.height = height
        self.video_path = video_path
        self.draw_synthetic_faces = draw_synthetic_faces
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cap: Optional[cv2.VideoCapture] = None
        self._frame_count = 0

        if self.video_path and os.path.exists(self.video_path):
            self._cap = cv2.VideoCapture(self.video_path)

    def _generate_synthetic_frame(self) -> np.ndarray:
        """Create a synthetic BGR frame with synthetic face shapes for benchmarking."""
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        # Background gradient / color change
        t = self._frame_count * 0.05
        bg_color = (int(40 + 20 * np.sin(t)), int(50 + 20 * np.cos(t)), 60)
        frame[:] = bg_color

        if self.draw_synthetic_faces:
            # Draw synthetic face 1 (moving across screen)
            x1 = int((self.width // 2 - 100) + 80 * np.sin(t))
            y1 = self.height // 2 - 50
            cv2.ellipse(frame, (x1, y1), (45, 60), 0, 0, 360, (180, 200, 230), -1)
            # Eyes
            cv2.circle(frame, (x1 - 15, y1 - 15), 6, (40, 40, 40), -1)
            cv2.circle(frame, (x1 + 15, y1 - 15), 6, (40, 40, 40), -1)
            # Mouth
            cv2.ellipse(frame, (x1, y1 + 20), (15, 8), 0, 0, 180, (40, 40, 40), 3)

            # Draw synthetic face 2 (stationary background)
            x2, y2 = self.width - 120, 100
            cv2.ellipse(frame, (x2, y2), (35, 48), 0, 0, 360, (170, 190, 220), -1)
            cv2.circle(frame, (x2 - 10, y2 - 10), 4, (40, 40, 40), -1)
            cv2.circle(frame, (x2 + 10, y2 - 10), 4, (40, 40, 40), -1)

        self._frame_count += 1
        return frame

    def get_next_frame(self) -> np.ndarray:
        if self._cap and self._cap.isOpened():
            ret, frame = self._cap.read()
            if not ret:
                self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = self._cap.read()
            if ret and frame is not None:
                if frame.shape[1] != self.width or frame.shape[0] != self.height:
                    frame = cv2.resize(frame, (self.width, self.height))
                return frame
        return self._generate_synthetic_frame()

    def close(self) -> None:
        if self._cap:
            self._cap.release()
            self._cap = None


# ---------------------------------------------------------------------------
# Benchmark Runner
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    """Benchmark runner testing 1, 5, 10, 25, 50, or 100 camera workloads."""

    def __init__(
        self,
        camera_count: int = 10,
        fps_per_camera: float = 15.0,
        duration_sec: float = 10.0,
        video_path: Optional[str] = None,
        process_callback: Optional[Callable[[str, np.ndarray], None]] = None,
    ) -> None:
        self.camera_count = camera_count
        self.fps_per_camera = fps_per_camera
        self.duration_sec = duration_sec
        self.video_path = video_path
        self.process_callback = process_callback
        self.collector = TelemetryCollector(history_window_sec=max(1.0, duration_sec))

    def run(self) -> Dict[str, Any]:
        """Execute benchmark and return metric summary."""
        logger.info(
            "Starting Benchmark: %d cameras, %s fps/cam, %s duration...",
            self.camera_count, self.fps_per_camera, self.duration_sec
        )
        self.collector.set_camera_count(self.camera_count)

        cameras = [
            SyntheticCameraStream(
                camera_id=f"benchmark_cam_{i+1:03d}",
                fps=self.fps_per_camera,
                video_path=self.video_path,
            )
            for i in range(self.camera_count)
        ]

        stop_event = threading.Event()
        workers: List[threading.Thread] = []

        def camera_loop(cam: SyntheticCameraStream) -> None:
            interval = 1.0 / self.fps_per_camera
            while not stop_event.is_set():
                start = time.monotonic()
                frame = cam.get_next_frame()
                self.collector.record_frame_received()

                if self.process_callback:
                    try:
                        self.process_callback(cam.camera_id, frame)
                    except Exception as exc:
                        logger.warning("Callback error: %s", exc)
                else:
                    # Mock detection latency calculation for raw benchmark baseline
                    time.sleep(0.001)

                elapsed = time.monotonic() - start
                sleep_time = max(0.0, interval - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        start_time = time.time()
        for cam in cameras:
            t = threading.Thread(target=camera_loop, args=(cam,), daemon=True)
            t.start()
            workers.append(t)

        time.sleep(self.duration_sec)
        stop_event.set()

        for t in workers:
            t.join(timeout=2.0)
        for cam in cameras:
            cam.close()

        metrics = self.collector.get_metrics()
        metrics["benchmark_config"] = {
            "camera_count": self.camera_count,
            "target_fps_per_camera": self.fps_per_camera,
            "duration_sec": self.duration_sec,
            "actual_duration_sec": round(time.time() - start_time, 2),
        }
        return metrics


def print_benchmark_report(results: Dict[str, Any]) -> None:
    """Print formatted benchmark result report to console."""
    cfg = results.get("benchmark_config", {})
    sys_m = results.get("system", {})
    pip_m = results.get("pipeline", {})
    gpu_m = sys_m.get("gpu", {})

    print("\n" + "=" * 65)
    print("      SCALABLE FACE RECOGNITION PIPELINE BENCHMARK REPORT      ")
    print("=" * 65)
    print(f" Camera Count              : {cfg.get('camera_count')}")
    print(f" Target FPS / Camera       : {cfg.get('target_fps_per_camera')}")
    print(f" Benchmark Duration        : {cfg.get('actual_duration_sec')}s")
    print("-" * 65)
    print(f" System CPU Usage          : {sys_m.get('cpu_percent')}%")
    print(f" Process RAM               : {sys_m.get('ram_process_mb')} MB")
    print(f" System RAM Used / Total   : {sys_m.get('ram_system_used_mb')} MB / {sys_m.get('ram_system_total_mb')} MB ({sys_m.get('ram_system_percent')}%)")
    print(f" Execution Provider        : {pip_m.get('active_provider')}")
    if gpu_m.get("available"):
        print(f" GPU Name                  : {gpu_m.get('name')}")
        print(f" GPU Utilization           : {gpu_m.get('gpu_percent')}%")
        print(f" VRAM Used / Total         : {gpu_m.get('vram_used_mb')} MB / {gpu_m.get('vram_total_mb')} MB ({gpu_m.get('vram_percent')}%)")
    else:
        print(f" GPU Acceleration          : Not Available (CPU Mode Active)")
    print("-" * 65)
    print(f" Total Frames Received     : {pip_m.get('received_frames')}")
    print(f" Total Frames Dropped      : {pip_m.get('dropped_frames')}")
    print(f" Detection Throughput      : {pip_m.get('detection_fps')} FPS")
    print(f" Avg Detection Latency     : {pip_m.get('detection_latency_ms')} ms")
    print(f" Recognition Throughput    : {pip_m.get('recognition_fps')} FPS")
    print(f" Avg Recognition Latency   : {pip_m.get('recognition_latency_ms')} ms")
    print(f" Queue Depth               : {pip_m.get('queue_depth')}")
    print(f" Active Tracks             : {pip_m.get('active_tracks')}")
    print(f" Total Full Model Calls    : {pip_m.get('full_model_inferences', {}).get('total')}")
    print(f"   - Student (Lightweight) : {pip_m.get('full_model_inferences', {}).get('student_lightweight')}")
    print(f"   - Teacher (buffalo_l)   : {pip_m.get('full_model_inferences', {}).get('teacher_buffalo_l')}")
    print(f" Recognition Calls Avoided : {pip_m.get('recognition_calls_avoided')}")
    print("=" * 65 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run face recognition pipeline benchmark.")
    parser.add_argument("--cameras", type=int, default=10, choices=[1, 5, 10, 25, 50, 100], help="Camera count")
    parser.add_argument("--fps", type=float, default=15.0, help="Target FPS per camera")
    parser.add_argument("--duration", type=float, default=5.0, help="Benchmark duration in seconds")
    parser.add_argument("--video", type=str, default=None, help="Optional local video file path")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    runner = BenchmarkRunner(
        camera_count=args.cameras,
        fps_per_camera=args.fps,
        duration_sec=args.duration,
        video_path=args.video,
    )
    res = runner.run()
    print_benchmark_report(res)
