from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from insightface.app import FaceAnalysis


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat(timespec="milliseconds")


def parse_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def decode_base64_image(image_base64: str) -> np.ndarray:
    try:
        payload = base64.b64decode(image_base64, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Invalid base64 image payload") from exc

    data = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail="Unable to decode image")
    return image


def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vector))
    if not math.isfinite(norm) or norm <= 0:
        return vector
    return vector / norm


def cosine_similarity(left: np.ndarray, right: np.ndarray) -> float:
    left_vec = normalize_embedding(left)
    right_vec = normalize_embedding(right)
    if left_vec.size == 0 or right_vec.size == 0:
        return -1.0
    denominator = float(np.linalg.norm(left_vec) * np.linalg.norm(right_vec))
    if denominator <= 0:
        return -1.0
    return float(np.dot(left_vec, right_vec) / denominator)


@dataclass
class FaceSample:
    label: str
    embeddings: list[list[float]]
    updatedAt: str

    @property
    def sample_count(self) -> int:
        return len(self.embeddings)


class FaceRegistry:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = threading.RLock()
        self._faces: dict[str, FaceSample] = {}

    def load(self) -> None:
        with self._lock:
            if not self.file_path.exists():
                self._faces = {}
                return

            try:
                payload = json.loads(self.file_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                self._faces = {}
                return

            faces = payload.get("faces", []) if isinstance(payload, dict) else []
            loaded: dict[str, FaceSample] = {}
            for entry in faces:
                if not isinstance(entry, dict):
                    continue
                label = str(entry.get("label", "")).strip()
                embeddings = entry.get("embeddings", [])
                if not label or not isinstance(embeddings, list):
                    continue
                normalized_embeddings: list[list[float]] = []
                for sample in embeddings:
                    if not isinstance(sample, list):
                        continue
                    vector = [float(value) for value in sample if isinstance(value, (int, float))]
                    if vector:
                        normalized_embeddings.append(vector)
                loaded[label] = FaceSample(
                    label=label,
                    embeddings=normalized_embeddings,
                    updatedAt=str(entry.get("updatedAt") or iso_now()),
                )
            self._faces = loaded

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "label": face.label,
                    "sampleCount": face.sample_count,
                    "updatedAt": face.updatedAt,
                }
                for face in sorted(self._faces.values(), key=lambda item: item.label.lower())
            ]

    def clear(self) -> None:
        with self._lock:
            self._faces = {}
            self._save_locked()

    def remove(self, label: str) -> bool:
        with self._lock:
            removed = self._faces.pop(label, None) is not None
            if removed:
                self._save_locked()
            return removed

    def register(self, label: str, embedding: np.ndarray) -> FaceSample:
        with self._lock:
            face = self._faces.get(label)
            if face is None:
                face = FaceSample(label=label, embeddings=[], updatedAt=iso_now())
            face.embeddings.append(normalize_embedding(embedding).astype(np.float32).tolist())
            face.updatedAt = iso_now()
            self._faces[label] = face
            self._save_locked()
            return face

    def match(self, embedding: np.ndarray, threshold: float) -> dict[str, Any] | None:
        with self._lock:
            best: dict[str, Any] | None = None
            for face in self._faces.values():
                scores = [cosine_similarity(embedding, np.asarray(sample, dtype=np.float32)) for sample in face.embeddings]
                if not scores:
                    continue
                scores.sort(reverse=True)
                top_scores = scores[:3]
                score = max(top_scores[0], sum(top_scores) / len(top_scores))
                if best is None or score > float(best["score"]):
                    best = {
                        "label": face.label,
                        "score": score,
                        "confidence": score,
                        "sampleCount": face.sample_count,
                    }
            if best is None or float(best["score"]) < threshold:
                return None
            return best

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._faces)

    def _save_locked(self) -> None:
        payload = {
            "version": 1,
            "updatedAt": iso_now(),
            "faces": [
                {
                    "label": face.label,
                    "embeddings": face.embeddings,
                    "updatedAt": face.updatedAt,
                    "sampleCount": face.sample_count,
                }
                for face in sorted(self._faces.values(), key=lambda item: item.label.lower())
            ],
        }
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.file_path.with_suffix(self.file_path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp_path.replace(self.file_path)


class FaceEngine:
    def __init__(self) -> None:
        snapshot_path = Path(os.getenv("SNAPSHOT_PATH", "./snapshots"))
        registry_path = Path(os.getenv("FACE_REGISTRY_PATH", str(snapshot_path / "known-faces-python.json")))
        self.snapshot_path = snapshot_path
        self.registry = FaceRegistry(registry_path)
        self.registry.load()

        self.match_threshold = parse_float_env(
            "PYTHON_MATCH_THRESHOLD",
            parse_float_env("MATCH_THRESHOLD", 0.45),
        )
        self.detection_threshold = parse_float_env(
            "PYTHON_DETECTION_THRESHOLD",
            parse_float_env("DETECTION_THRESHOLD", 0.5),
        )
        self.snapshot_cooldown_ms = parse_int_env("SNAPSHOT_COOLDOWN_MS", 10_000)
        self.det_size = (
            parse_int_env("INSIGHTFACE_DET_WIDTH", 640),
            parse_int_env("INSIGHTFACE_DET_HEIGHT", 640),
        )
        self.model_name = os.getenv("INSIGHTFACE_MODEL", "buffalo_l")
        self.model_dir = os.getenv("INSIGHTFACE_MODEL_DIR") or str(
            Path.home() / ".cache" / "insightface"
        )
        self._model_lock = threading.Lock()
        self._snapshot_lock = threading.Lock()
        self._last_snapshot_at = 0.0
        self._model = self._load_model()

    def _load_model(self) -> FaceAnalysis:
        providers = [provider.strip() for provider in os.getenv("INSIGHTFACE_PROVIDERS", "CPUExecutionProvider").split(",") if provider.strip()]
        model = FaceAnalysis(name=self.model_name, root=self.model_dir, providers=providers)
        model.prepare(ctx_id=-1, det_size=self.det_size)
        return model

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "ready": True,
            "model": self.model_name,
            "faces": self.registry.count,
            "timestamp": iso_now(),
        }

    def recognize(self, image: np.ndarray) -> dict[str, Any]:
        with self._model_lock:
            faces = self._model.get(image)

        detected = [self._serialize_face(face) for face in self._filter_faces(faces)]
        snapshot = self._maybe_save_snapshot(image, detected)
        state = "faces detected" if detected else "no face detected"
        if snapshot is not None:
            state = "snapshot saved"
        return {
            "state": state,
            "faces": detected,
            "snapshot": snapshot,
        }

    def register(self, label: str, image: np.ndarray) -> dict[str, Any]:
        label = label.strip()
        if not label:
            raise HTTPException(status_code=400, detail="Label is required")

        with self._model_lock:
            faces = self._filter_faces(self._model.get(image))

        if not faces:
            raise HTTPException(status_code=400, detail="No face found in the current frame.")

        face = max(faces, key=lambda item: float(item.bbox[2] - item.bbox[0]) * float(item.bbox[3] - item.bbox[1]) * float(getattr(item, "det_score", 0.0)))
        embedding = self._embedding_for(face)
        if embedding is None:
            raise HTTPException(status_code=400, detail="Face embedding could not be generated.")

        sample = self.registry.register(label, embedding)
        return {
            "label": sample.label,
            "sampleCount": sample.sample_count,
            "updatedAt": sample.updatedAt,
        }

    def list_faces(self) -> list[dict[str, Any]]:
        return self.registry.list()

    def remove_face(self, label: str) -> bool:
        return self.registry.remove(label)

    def clear_faces(self) -> None:
        self.registry.clear()

    def _filter_faces(self, faces: list[Any]) -> list[Any]:
        filtered = []
        for face in faces:
            if float(getattr(face, "det_score", 0.0)) < self.detection_threshold:
                continue
            if self._embedding_for(face) is None:
                continue
            filtered.append(face)
        return filtered

    def _embedding_for(self, face: Any) -> np.ndarray | None:
        embedding = getattr(face, "normed_embedding", None)
        if embedding is None:
            embedding = getattr(face, "embedding", None)
        if embedding is None:
            return None
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size == 0:
            return None
        return normalize_embedding(vector)

    def _serialize_face(self, face: Any) -> dict[str, Any]:
        embedding = self._embedding_for(face)
        assert embedding is not None
        match = self.registry.match(embedding, self.match_threshold)
        bbox = [float(value) for value in getattr(face, "bbox", [0, 0, 0, 0])]
        x1, y1, x2, y2 = bbox[:4]
        confidence = float(getattr(face, "det_score", 0.0))
        return {
            "confidence": confidence,
            "box": {
                "x": x1,
                "y": y1,
                "width": max(0.0, x2 - x1),
                "height": max(0.0, y2 - y1),
            },
            "match": match,
        }

    def _maybe_save_snapshot(self, image: np.ndarray, faces: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not faces:
            return None

        now_ms = datetime.now(tz=timezone.utc).timestamp() * 1000.0
        with self._snapshot_lock:
            if now_ms - self._last_snapshot_at < self.snapshot_cooldown_ms:
                return None

        best_face = max(faces, key=lambda face: float(face["confidence"]))
        timestamp = iso_now().replace(":", "-").replace("+", "-")
        filename = f"face-{timestamp}.jpg"
        path = self.snapshot_path / filename
        self.snapshot_path.mkdir(parents=True, exist_ok=True)
        ok = cv2.imwrite(str(path), image)
        if not ok:
            return None
        with self._snapshot_lock:
            self._last_snapshot_at = now_ms
        return {
            "path": str(path),
            "timestamp": iso_now(),
            "confidence": float(best_face["confidence"]),
        }


class RegisterRequest(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    imageBase64: str


class RecognizeRequest(BaseModel):
    imageBase64: str


engine = FaceEngine()
app = FastAPI(title="Python Face Recognizer", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return engine.health()


@app.post("/recognize")
async def recognize(payload: RecognizeRequest) -> dict[str, Any]:
    image = decode_base64_image(payload.imageBase64)
    result = await asyncio.to_thread(engine.recognize, image)
    return result


@app.post("/register")
async def register(payload: RegisterRequest) -> dict[str, Any]:
    image = decode_base64_image(payload.imageBase64)
    result = await asyncio.to_thread(engine.register, payload.label.strip(), image)
    return result


@app.get("/faces")
async def faces() -> dict[str, Any]:
    return {"faces": await asyncio.to_thread(engine.list_faces)}


@app.delete("/faces/{label}")
async def delete_face(label: str) -> dict[str, Any]:
    trimmed = label.strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Label is required")
    removed = await asyncio.to_thread(engine.remove_face, trimmed)
    return {"ok": True, "removed": removed}


@app.post("/faces/clear")
async def clear_faces() -> dict[str, Any]:
    await asyncio.to_thread(engine.clear_faces)
    return {"ok": True}
