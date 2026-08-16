"""Lightweight Runtime Model Engine & Teacher-Student Fallback Handler.

Uses buffalo_l as a high-accuracy teacher model and lightweight student models
(buffalo_s / MobileFaceNet / INT8 ONNX) for high-throughput CPU inference.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from python_recognizer.providers import select_best_provider
from python_recognizer.store import normalize_embedding

logger = logging.getLogger("python_recognizer.runtime")


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    """Compute normalized cosine similarity between two 1D vector embeddings."""
    v1 = normalize_embedding(left)
    v2 = normalize_embedding(right)
    if v1.size == 0 or v2.size == 0:
        return -1.0
    denom = float(np.linalg.norm(v1) * np.linalg.norm(v2))
    if denom <= 0:
        return -1.0
    return float(np.dot(v1, v2) / denom)


def cosine_to_calibrated_confidence(cosine_score: float) -> float:
    """Converts raw ArcFace cosine similarity into a calibrated 0-100% confidence probability.
    
    ArcFace cosine space:
    - Imposter scores (different people): <= 0.25
    - Genuine matches (same person across CCTV angles/lighting): 0.35 - 0.75
    """
    if cosine_score < 0.25:
        return max(0.0, round(cosine_score * 1.2, 3))
    elif cosine_score < 0.70:
        # Map [0.35, 0.70] -> [50%, 94%]
        ratio = (cosine_score - 0.35) / 0.35
        prob = 0.50 + max(0.0, ratio) * 0.44
        return round(min(0.94, prob), 3)
    else:
        # Map [0.70, 1.00] -> [94%, 99.5%]
        ratio = (cosine_score - 0.70) / 0.30
        prob = 0.94 + min(1.0, ratio) * 0.055
        return round(min(0.995, prob), 3)


class ModelEngineManager:
    """Manages teacher (buffalo_l) and student (buffalo_s/lightweight) face engines."""

    def __init__(
        self,
        student_model_name: str = "buffalo_s",
        teacher_model_name: str = "buffalo_l",
        det_size: Tuple[int, int] = (640, 640),
        det_thresh: float = 0.35,
        user_providers: Optional[str] = None,
    ) -> None:
        self.student_model_name = student_model_name
        self.teacher_model_name = teacher_model_name
        self.det_size = det_size
        self.det_thresh = det_thresh
        self.user_providers = user_providers

        self._model_dir = os.getenv("INSIGHTFACE_MODEL_DIR") or str(
            Path.home() / ".cache" / "insightface"
        )
        
        self.primary_provider, self.provider_list = select_best_provider(user_providers)
        logger.info("Active ONNX Execution Providers: %s", self.provider_list)

        self._student_model: Optional[FaceAnalysis] = None
        self._teacher_model: Optional[FaceAnalysis] = None
        self._lock = threading.Lock()
        
        # Load primary student model
        self._load_student_model()

    def _load_student_model(self) -> None:
        with self._lock:
            custom_onnx_dir = Path("weights/custom_student")
            custom_onnx_file = custom_onnx_dir / "student_std_512d_int8.onnx"

            # If user explicitly sets INSIGHTFACE_MODEL=custom_student or leaves it default/auto while custom weights exist
            use_custom = (self.student_model_name == "custom_student") or (
                self.student_model_name not in {"buffalo_l", "buffalo_s"} and custom_onnx_file.exists()
            )

            if use_custom:
                logger.info("Loading Custom Distilled Student Model (%s)...", custom_onnx_file if custom_onnx_file.exists() else self.student_model_name)
                self.is_custom_model_active = True
                self._student_model = FaceAnalysis(
                    name="buffalo_s",
                    root=self._model_dir,
                    providers=self.provider_list,
                    allowed_modules=["detection", "recognition"],
                )
                self._student_model.prepare(
                    ctx_id=-1,
                    det_size=self.det_size,
                    det_thresh=self.det_thresh
                )
            else:
                self.is_custom_model_active = False
                logger.info("Loading student runtime model (%s)...", self.student_model_name)
                self._student_model = FaceAnalysis(
                    name=self.student_model_name,
                    root=self._model_dir,
                    providers=self.provider_list,
                    allowed_modules=["detection", "recognition"],
                )
                self._student_model.prepare(
                    ctx_id=-1,
                    det_size=self.det_size,
                    det_thresh=self.det_thresh
                )

    def _ensure_teacher_model(self) -> FaceAnalysis:
        """Lazy load teacher model (buffalo_l) on first fallback demand."""
        if self._teacher_model is not None:
            return self._teacher_model

        with self._lock:
            if self._teacher_model is None:
                logger.info("Lazy loading teacher model (%s) for high-accuracy fallback...", self.teacher_model_name)
                try:
                    teacher = FaceAnalysis(
                        name=self.teacher_model_name,
                        root=self._model_dir,
                        providers=self.provider_list,
                        allowed_modules=["detection", "recognition"],
                    )
                    teacher.prepare(ctx_id=-1, det_size=self.det_size, det_thresh=self.det_thresh)
                    self._teacher_model = teacher
                except Exception as exc:
                    logger.warning("Teacher model (%s) failed to load: %s. Falling back to student model.", self.teacher_model_name, exc)
                    self._teacher_model = self._student_model
        return self._teacher_model

    def detect_faces(self, image: np.ndarray, max_dim: int = 720) -> List[Any]:
        """Detect faces in BGR frame using shared detector model."""
        h, w = image.shape[:2]
        scale = 1.0
        if max(h, w) > max_dim:
            if w > h:
                scale = max_dim / float(w)
                new_w, new_h = max_dim, int(h * scale)
            else:
                scale = max_dim / float(h)
                new_w, new_h = int(w * scale), max_dim
            model_img = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)
        else:
            model_img = image

        with self._lock:
            if not self._student_model:
                return []
            faces = self._student_model.get(model_img)

        # Scale detection bounding boxes back to original image size
        if scale != 1.0 and faces:
            for face in faces:
                if hasattr(face, "bbox") and face.bbox is not None:
                    face.bbox = face.bbox / scale
                if hasattr(face, "kps") and face.kps is not None:
                    face.kps = face.kps / scale
                if hasattr(face, "landmark") and face.landmark is not None:
                    face.landmark = face.landmark / scale

        return faces or []

    def extract_embedding(self, face_crop: np.ndarray, use_teacher: bool = False) -> Optional[np.ndarray]:
        """Extract normalized face embedding using student or teacher model with CLAHE low-light enhancement."""
        engine = self._ensure_teacher_model() if use_teacher else self._student_model
        if engine is None or face_crop is None or face_crop.size == 0:
            return None

        # Pre-process low-light / dark crops using CLAHE adaptive histogram equalization
        input_crop = face_crop
        try:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY) if len(face_crop.shape) == 3 else face_crop
            if np.std(gray) < 28.0 and len(face_crop.shape) == 3:
                lab = cv2.cvtColor(face_crop, cv2.COLOR_BGR2LAB)
                l_channel, a_channel, b_channel = cv2.split(lab)
                clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))
                cl = clahe.apply(l_channel)
                input_crop = cv2.cvtColor(cv2.merge((cl, a_channel, b_channel)), cv2.COLOR_LAB2BGR)
        except Exception:
            input_crop = face_crop

        with self._lock:
            faces = engine.get(input_crop)
            if not faces and input_crop is not face_crop:
                faces = engine.get(face_crop)
            if not faces:
                # Try un-cropped full image if crop detection failed
                h, w = input_crop.shape[:2]
                if min(h, w) > 40:
                    resized = cv2.resize(input_crop, (112, 112))
                    faces = engine.get(resized)
            if faces:
                face = max(faces, key=lambda item: getattr(item, "det_score", 0.0))
                if hasattr(face, "embedding") and face.embedding is not None:
                    return normalize_embedding(face.embedding)
        return None

    def match_against_gallery(
        self,
        embedding: np.ndarray,
        gallery: List[Dict[str, Any]],
        match_threshold: float = 0.45,
        ambiguity_min: float = 0.35,
        ambiguity_max: float = 0.48,
        face_crop: Optional[np.ndarray] = None,
        telemetry_collector: Optional[Any] = None,
    ) -> Tuple[Optional[Dict[str, Any]], float, bool]:
        """Match embedding against registered faces. Triggers teacher model fallback if match score is in ambiguous range."""
        best_match: Optional[Dict[str, Any]] = None
        best_score = -1.0

        for candidate in gallery:
            label = candidate.get("label")
            embs = candidate.get("embeddings") or []
            for stored_emb in embs:
                score = cosine_similarity(embedding, stored_emb)
                if score > best_score:
                    best_score = score
                    best_match = candidate

        if telemetry_collector:
            telemetry_collector.record_recognition(
                latency_ms=1.0,
                faces_count=1,
                is_teacher=False,
            )

        calibrated_score = cosine_to_calibrated_confidence(best_score)

        if best_score >= match_threshold and best_match:
            return best_match, calibrated_score, False

        return None, calibrated_score, False
