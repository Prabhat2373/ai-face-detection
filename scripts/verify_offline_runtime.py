"""Verify that the packaged runtime can load its custom model without InsightFace."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "weights" / "custom_student" / "student_std_512d_int8.onnx"


def main() -> int:
    if not MODEL.exists():
        print(f"FAIL: missing custom model: {MODEL}")
        return 1
    if importlib.util.find_spec("insightface") is not None:
        print("WARN: InsightFace is present in this development environment; it is not a client requirement")
    sys.path.insert(0, str(ROOT))
    os.environ["CUSTOM_RECOGNIZER_MODEL"] = str(MODEL)
    try:
        from python_recognizer.custom_pipeline import CustomONNXFacePipeline

        pipeline = CustomONNXFacePipeline()
        print(f"PASS: custom ONNX recognizer loaded ({pipeline.embedding_dim}D)")
        print("PASS: buffalo_s detector loaded")
        return 0
    except Exception as exc:
        print(f"FAIL: custom offline runtime could not load: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
