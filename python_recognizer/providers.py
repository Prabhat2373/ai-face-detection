"""Hardware Acceleration and Provider Management for Face Recognition Engine.

Detects and selects execution providers (CUDA, TensorRT, DirectML, CPU) and FFmpeg hardware video decoders.
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from typing import Any, Dict, List, Tuple

logger = logging.getLogger("python_recognizer.providers")


def get_available_onnx_providers() -> List[str]:
    """Detect available ONNX Runtime execution providers in priority order."""
    available: List[str] = []
    try:
        import onnxruntime as ort
        installed = ort.get_available_providers()
        
        # Priority order
        candidates = [
            "TensorRTExecutionProvider",
            "CUDAExecutionProvider",
            "DirectMLExecutionProvider",
            "CoreMLExecutionProvider",
            "CPUExecutionProvider",
        ]
        
        for cand in candidates:
            if cand in installed:
                available.append(cand)
    except Exception as exc:
        logger.warning("Error querying ONNX Runtime providers: %s", exc)
        available = ["CPUExecutionProvider"]

    if not available:
        available = ["CPUExecutionProvider"]
        
    return available


def select_best_provider(user_configured: str | None = None) -> Tuple[str, List[str]]:
    """Select primary active provider and ordered fallback provider list."""
    available = get_available_onnx_providers()
    
    if user_configured:
        configured_list = [p.strip() for p in user_configured.split(",") if p.strip()]
        valid_configured = [p for p in configured_list if p in available]
        if valid_configured:
            primary = valid_configured[0]
            return primary, valid_configured

    primary = available[0]
    return primary, available


def detect_ffmpeg_hwaccel() -> Dict[str, Any]:
    """Detect platform hardware video decoding flags for FFmpeg."""
    system_name = platform.system().lower()
    
    # macOS Apple Silicon / Intel
    if system_name == "darwin":
        return {
            "supported": True,
            "codec": "h264_videotoolbox",
            "args": ["-hwaccel", "videotoolbox"],
        }
        
    # Windows
    if system_name == "windows":
        return {
            "supported": True,
            "codec": "h264",
            "args": ["-hwaccel", "d3d11va"],
        }
        
    # Linux (check for NVDEC or VAAPI)
    if system_name == "linux":
        try:
            res = subprocess.run(["ffmpeg", "-hwaccels"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2)
            if "cuda" in res.stdout or "nvdec" in res.stdout:
                return {
                    "supported": True,
                    "codec": "h264_nvdec",
                    "args": ["-hwaccel", "cuda"],
                }
            if "vaapi" in res.stdout:
                return {
                    "supported": True,
                    "codec": "h264_vaapi",
                    "args": ["-hwaccel", "vaapi"],
                }
        except Exception:
            pass

    return {
        "supported": False,
        "codec": "h264",
        "args": [],
    }
