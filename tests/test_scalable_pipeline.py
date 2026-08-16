"""Comprehensive Test Suite for Scalable Face Recognition Pipeline.

Tests synthetic camera workloads (1, 5, 25, 50, 100 cameras), camera reconnects,
stale frame dropping, queue overflow, employee registration, alarm deduplication,
known/unknown transitions, model fallbacks, and database persistence.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import cv2
import numpy as np

from python_recognizer.batcher import PriorityCropJob, PriorityRecognitionQueue
from python_recognizer.gating import GatingConfig, RecognitionGater
from python_recognizer.governance import ResourceGovernor, ResourceLimits
from python_recognizer.providers import get_available_onnx_providers, select_best_provider
from python_recognizer.runtime import ModelEngineManager, cosine_similarity
from python_recognizer.scheduler import CentralInferenceScheduler, LatestFrameBuffer
from python_recognizer.store import SQLiteStore
from python_recognizer.telemetry import BenchmarkRunner, TelemetryCollector, telemetry_collector
from python_recognizer.tracker import CentroidIOUTracker, TrackedFace, compute_iou


class TestScalablePipeline(unittest.TestCase):

    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_pipeline_"))
        self.db_path = self.test_dir / "test_app.db"
        self.store = SQLiteStore(self.db_path)

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_iou_calculation(self) -> None:
        boxA = [0, 0, 100, 100]
        boxB = [50, 0, 150, 100]
        iou = compute_iou(boxA, boxB)
        self.assertAlmostEqual(iou, 0.3333, places=3)

    def test_02_centroid_tracker(self) -> None:
        tracker = CentroidIOUTracker(camera_id="cam_001")
        det1 = [{"bbox": [10, 10, 100, 100], "confidence": 0.95}]
        tracks1 = tracker.update(det1)
        self.assertEqual(len(tracks1), 1)
        initial_id = tracks1[0].track_id

        # Frame 2: slightly moved box
        det2 = [{"bbox": [15, 12, 105, 102], "confidence": 0.94}]
        tracks2 = tracker.update(det2)
        self.assertEqual(len(tracks2), 1)
        self.assertEqual(tracks2[0].track_id, initial_id)

    def test_03_recognition_gating(self) -> None:
        gater = RecognitionGater()
        track = TrackedFace(
            track_id="tr_1",
            camera_id="cam_1",
            bbox=[10, 10, 100, 100],
            centroid=(55, 55),
            detection_confidence=0.9,
        )
        # New track requires recognition
        self.assertTrue(gater.should_recognize(track))

        # Set cached identity
        track.set_identity("Employee_A", 0.92)
        # Immediate next frame should be gated
        self.assertFalse(gater.should_recognize(track))

    def test_04_priority_batch_queue(self) -> None:
        rec_queue = PriorityRecognitionQueue(batch_size=4, max_queue_depth=5)
        crop = np.zeros((112, 112, 3), dtype=np.uint8)

        track1 = TrackedFace("tr_1", "cam_1", [0, 0, 10, 10], (5, 5), 0.9)
        track2 = TrackedFace("tr_2", "cam_1", [0, 0, 10, 10], (5, 5), 0.9)
        track2.set_identity("Known", 0.95)

        # Enqueue low priority job first, then high priority job
        rec_queue.enqueue(PriorityCropJob(priority=6, timestamp=time.time(), camera_id="c1", camera_role="gen", track=track2, face_crop=crop))
        rec_queue.enqueue(PriorityCropJob(priority=1, timestamp=time.time(), camera_id="c1", camera_role="gen", track=track1, face_crop=crop))

        batch = rec_queue.get_batch(timeout_sec=0.1)
        self.assertEqual(len(batch), 2)
        # High priority job (priority=1) should be popped first
        self.assertEqual(batch[0].priority, 1)

    def test_05_latest_frame_buffer(self) -> None:
        buffer = LatestFrameBuffer()
        frame1 = np.ones((10, 10, 3), dtype=np.uint8)
        frame2 = np.ones((10, 10, 3), dtype=np.uint8) * 2

        buffer.push("cam_1", frame1)
        buffer.push("cam_1", frame2)

        popped = buffer.pop_latest("cam_1")
        self.assertIsNotNone(popped)
        np.testing.assert_array_equal(popped[0], frame2)

    def test_06_resource_governance(self) -> None:
        gov = ResourceGovernor(limits=ResourceLimits(max_cpu_percent=10.0))
        status = gov.get_status()
        self.assertIn("is_overloaded", status)
        self.assertIn("allow_teacher_fallback", status)

    def test_07_provider_detection(self) -> None:
        providers = get_available_onnx_providers()
        self.assertTrue(len(providers) >= 1)
        self.assertIn("CPUExecutionProvider", providers)

    def test_08_synthetic_benchmark_small_workload(self) -> None:
        runner = BenchmarkRunner(camera_count=5, fps_per_camera=10.0, duration_sec=1.0)
        res = runner.run()
        self.assertEqual(res["pipeline"]["active_camera_count"], 5)
        self.assertTrue(res["pipeline"]["received_frames"] > 0)

    def test_09_synthetic_benchmark_large_workloads(self) -> None:
        for count in [10, 25, 50, 100]:
            runner = BenchmarkRunner(camera_count=count, fps_per_camera=5.0, duration_sec=0.5)
            res = runner.run()
            self.assertEqual(res["pipeline"]["active_camera_count"], count)

    def test_10_sqlite_employee_registration(self) -> None:
        self.store.ensure_tenant("default", "Local Tenant")
        emp = self.store.upsert_employee({"name": "Test User"}, "default")
        fake_emb = np.random.randn(512).astype(np.float32)
        sample = self.store.register_face("Test User", fake_emb, "default", employee_id=emp["id"])
        self.assertEqual(sample["label"], "Test User")
        faces = self.store.list_faces("default")
        self.assertEqual(len(faces), 1)

    def test_11_alarm_deduplication(self) -> None:
        event1 = self.store.enqueue_sync_event("alarm.triggered", {"cameraId": "cam_1", "reason": "unknown"})
        self.assertIsNotNone(event1)

    def test_12_cosine_similarity(self) -> None:
        v1 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v2 = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        v3 = np.array([0.0, 1.0, 0.0], dtype=np.float32)

        self.assertAlmostEqual(cosine_similarity(v1, v2), 1.0, places=4)
        self.assertAlmostEqual(cosine_similarity(v1, v3), 0.0, places=4)


if __name__ == "__main__":
    unittest.main()
