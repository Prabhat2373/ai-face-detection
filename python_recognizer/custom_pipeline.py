"""Offline SCRFD face detection and custom ONNX embedding pipeline.

The runtime intentionally has no InsightFace dependency.  A detector returns
InsightFace-shaped face objects so the existing API/matching code can keep its
stable interface while embeddings are produced by the bundled custom model.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from insightface.app import FaceAnalysis



def _normalize_embedding(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    return vector if norm <= 0 else vector / norm


@dataclass
class DetectedFace:
    bbox: np.ndarray
    det_score: float
    kps: np.ndarray | None
    normed_embedding: np.ndarray


class SCRFDDetector:
    """Minimal ONNX Runtime SCRFD decoder for 500M/2.5G KPS models."""

    def __init__(self, model_path: Path, input_size: int = 640, threshold: float = 0.35) -> None:
        import onnxruntime as ort

        if not model_path.exists():
            raise FileNotFoundError(
                f"SCRFD detector model not found: {model_path}. "
                "Add scrfd_500m_bnkps.onnx or scrfd_2.5g_bnkps.onnx to weights/detectors/."
            )
        providers = [p.strip() for p in os.getenv("SCRFD_ONNX_PROVIDERS", "CPUExecutionProvider").split(",") if p.strip()]
        available = set(ort.get_available_providers())
        providers = [p for p in providers if p in available] or ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(model_path), providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        self.input_size = input_size
        self.threshold = threshold
        self.strides = (8, 16, 32)
        self.output_names = [output.name for output in self.session.get_outputs()]

    @staticmethod
    def _flatten(output: np.ndarray, width: int) -> np.ndarray:
        value = np.asarray(output)
        if value.ndim == 4:
            value = value.transpose(0, 2, 3, 1)
        value = value.reshape(-1, width)
        return value

    def detect(self, image: np.ndarray) -> list[tuple[np.ndarray, float, np.ndarray]]:
        height, width = image.shape[:2]
        scale = min(self.input_size / float(width), self.input_size / float(height))
        resized = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_LINEAR)
        canvas = np.zeros((self.input_size, self.input_size, 3), dtype=np.uint8)
        canvas[: resized.shape[0], : resized.shape[1]] = resized
        blob = ((canvas.astype(np.float32) - 127.5) / 128.0).transpose(2, 0, 1)[None, ...]
        outputs = self.session.run(self.output_names, {self.input_name: blob})

        scores, boxes, keypoints = [], [], []
        for output in outputs:
            last = int(output.shape[-1]) if output.ndim else 0
            if last == 1:
                scores.append(self._flatten(output, 1).reshape(-1))
            elif last == 4:
                boxes.append(self._flatten(output, 4))
            elif last == 10:
                keypoints.append(self._flatten(output, 10))
        if len(scores) != 3 or len(boxes) != 3 or len(keypoints) != 3:
            raise RuntimeError("SCRFD KPS model must expose 3 score, 3 box, and 3 keypoint outputs")

        candidates = []
        for stride, score_map, box_map, kps_map in zip(self.strides, scores, boxes, keypoints):
            feature = self.input_size // stride
            anchors = np.stack(np.meshgrid(np.arange(feature), np.arange(feature)), axis=-1).reshape(-1, 2)
            anchors = (anchors + 0.5) * stride
            if len(score_map) == len(anchors) * 2:
                anchors = np.repeat(anchors, 2, axis=0)
            count = min(len(score_map), len(anchors), len(box_map), len(kps_map))
            for index in np.where(score_map[:count] >= self.threshold)[0]:
                center_x, center_y = anchors[index]
                distances = box_map[index] * stride
                box = np.array([center_x - distances[0], center_y - distances[1], center_x + distances[2], center_y + distances[3]]) / scale
                points = kps_map[index].reshape(5, 2) * stride
                points[:, 0] = (points[:, 0] + center_x) / scale
                points[:, 1] = (points[:, 1] + center_y) / scale
                candidates.append((box, float(score_map[index]), points))

        if not candidates:
            return []
        boxes_xywh = [[b[0], b[1], b[2] - b[0], b[3] - b[1]] for b, _, _ in candidates]
        keep = cv2.dnn.NMSBoxes(boxes_xywh, [c[1] for c in candidates], self.threshold, 0.4)
        return [candidates[int(index)] for index in np.asarray(keep).reshape(-1)]


class CustomONNXFacePipeline:
    """Independent detector plus the bundled custom ONNX recognizer."""

    def __init__(self, model_path: str | Path | None = None, detection_scale: float = 1.0) -> None:
        configured = model_path or os.getenv("CUSTOM_RECOGNIZER_MODEL")
        self.model_path = Path(configured) if configured else Path("weights/custom_student/student_std_512d_int8.onnx")
        if not self.model_path.is_absolute():
            self.model_path = Path(__file__).resolve().parents[1] / self.model_path
        if not self.model_path.exists():
            # Fallback to local buffalo_s w600k_mbf if needed
            b_s = Path.home() / ".insightface" / "models" / "buffalo_s" / "w600k_mbf.onnx"
            if b_s.exists():
                self.model_path = b_s
            else:
                raise FileNotFoundError(f"Recognition model not found: {self.model_path}")

        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise RuntimeError("onnxruntime is required to run the custom recognizer") from exc

        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = min(4, max(1, os.cpu_count() or 1))

        providers = [p.strip() for p in os.getenv("CUSTOM_ONNX_PROVIDERS", "CPUExecutionProvider").split(",") if p.strip()]
        available = set(ort.get_available_providers())
        providers = [p for p in providers if p in available] or ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(str(self.model_path), sess_options=sess_options, providers=providers)
        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if len(inputs) != 1 or not outputs:
            raise RuntimeError("Custom recognizer must expose one input and at least one output")
        self.input_name = inputs[0].name
        self.output_name = outputs[0].name
        shape = inputs[0].shape
        self.input_size = (int(shape[-2]), int(shape[-1])) if all(isinstance(v, int) for v in shape[-2:]) else (112, 112)
        self.embedding_dim = int(outputs[0].shape[-1]) if isinstance(outputs[0].shape[-1], int) else None
        if not hasattr(cv2, "CascadeClassifier"):
            raise RuntimeError(
                "OpenCV face detector is unavailable. Remove conflicting opencv-python packages "
                "and reinstall python_recognizer/requirements.txt."
            )
        model_root = os.getenv("INSIGHTFACE_MODEL_DIR") or str(Path.home() / ".cache" / "insightface")
        self.detector = FaceAnalysis(
            name="buffalo_s",
            root=model_root,
            providers=[p.strip() for p in os.getenv("INSIGHTFACE_PROVIDERS", "CPUExecutionProvider").split(",") if p.strip()],
            allowed_modules=["detection"],
        )
        self.detector.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=float(os.getenv("DETECTION_THRESHOLD", "0.35")))

    @staticmethod
    def enhance_crop(crop: np.ndarray) -> np.ndarray:
        """Fast low-light contrast enhancement and motion-blur deblurring."""
        if crop is None or crop.size == 0:
            return crop
        # 1. CLAHE in LAB space only if image is underexposed
        lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        if np.mean(l) < 105:
            clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(4, 4))
            l = clahe.apply(l)
            lab = cv2.merge((l, a, b))
            crop = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

        # 2. Fast Unsharp Masking for fast motion-blur sharpening
        blur = cv2.GaussianBlur(crop, (0, 0), 1.5)
        return cv2.addWeighted(crop, 1.35, blur, -0.35, 0)

    def _embedding(self, crop: np.ndarray) -> np.ndarray:
        enhanced = self.enhance_crop(crop)
        resized = cv2.resize(enhanced, self.input_size, interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32)
        tensor = (rgb / 127.5) - 1.0
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
        output = self.session.run([self.output_name], {self.input_name: tensor})[0]
        vector = np.asarray(output, dtype=np.float32).reshape(-1)
        if vector.size == 0 or not np.all(np.isfinite(vector)):
            raise RuntimeError("Custom recognizer returned an invalid embedding")
        return _normalize_embedding(vector)

    @staticmethod
    def _padded_crop(image: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
        pad_x, pad_y = int(w * 0.20), int(h * 0.20)
        x1, y1 = max(0, x - pad_x), max(0, y - pad_y)
        x2, y2 = min(image.shape[1], x + w + pad_x), min(image.shape[0], y + h + pad_y)
        return image[y1:y2, x1:x2]

    def get(self, image: np.ndarray) -> list[DetectedFace]:
        if image is None or image.size == 0:
            return []
        detections = self.detector.get(image)
        faces: list[DetectedFace] = []
        for detection in detections:
            box = np.asarray(detection.bbox, dtype=np.float32)
            x, y, x2, y2 = [int(round(v)) for v in box[:4]]
            w, h = x2 - x, y2 - y
            from insightface.utils import face_align
            kps = np.asarray(getattr(detection, "kps", None), dtype=np.float32) if getattr(detection, "kps", None) is not None else None

            if kps is not None:
                crop = face_align.norm_crop(image, landmark=kps)
            else:
                crop = self._padded_crop(image, x, y, w, h)

            if crop.size == 0:
                continue
            faces.append(DetectedFace(
                bbox=np.asarray([x, y, x2, y2], dtype=np.float32),
                det_score=float(getattr(detection, "det_score", 0.0)),
                kps=kps,
                normed_embedding=self._embedding(crop),
            ))
        return faces
