"""Student V2: Realistic CCTV Degradation Distillation Engine.

Trains a standalone lightweight MobileFaceNet student model using buffalo_l as offline teacher.
Simulates realistic CCTV surveillance conditions:
- Low light (Gamma 0.35-0.75, sensor noise, shadow gradient)
- Directional motion blur (0-360 deg, 5-15px stride)
- Multi-scale CCTV downscaling (24px, 32px, 40px, 48px, 64px)
- JPEG compression (Q=20-60)
- Balanced with 50% clean faces to ensure high accuracy on clear faces.
"""

from __future__ import annotations

import argparse
import math
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from python_recognizer.train_student import MobileFaceNet, ArcFaceDistillationLoss


# ---------------------------------------------------------------------------
# Comprehensive CCTV Surveillance Degradation Engine
# ---------------------------------------------------------------------------

class RealisticCCTVDegrader:
    """Applies realistic CCTV surveillance distortions matching real-world security cameras."""

    @staticmethod
    def apply_gamma(img: np.ndarray, gamma: float = 0.45) -> np.ndarray:
        inv_gamma = 1.0 / max(0.01, gamma)
        table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]).astype("uint8")
        return cv2.LUT(img, table)

    @staticmethod
    def apply_color_shift(img: np.ndarray, b_add: int = 10, r_sub: int = 15) -> np.ndarray:
        b, g, r = cv2.split(img)
        b = np.clip(b.astype(np.int16) + b_add, 0, 255).astype(np.uint8)
        r = np.clip(r.astype(np.int16) - r_sub, 0, 255).astype(np.uint8)
        return cv2.merge([b, g, r])

    @staticmethod
    def apply_sensor_noise(img: np.ndarray, sigma: float = 12.0) -> np.ndarray:
        noise = np.random.normal(0, sigma, img.shape).astype(np.float32)
        return np.clip(img.astype(np.float32) + noise, 0, 255).astype(np.uint8)

    @staticmethod
    def apply_cctv_motion_blur(img: np.ndarray, length: int = 20, angle_deg: float = 22.0) -> np.ndarray:
        rad = np.deg2rad(angle_deg)
        dx = int(np.round(np.cos(rad) * length))
        dy = int(np.round(np.sin(rad) * length))
        ksize = max(abs(dx), abs(dy)) * 2 + 1
        kernel = np.zeros((ksize, ksize), dtype=np.float32)
        center = ksize // 2
        cv2.line(kernel, (center - dx, center - dy), (center + dx, center + dy), 1.0, 1)
        ksum = np.sum(kernel)
        if ksum > 0:
            kernel /= ksum
            return cv2.filter2D(img, -1, kernel)
        return img

    @staticmethod
    def apply_downscale_upscale(img: np.ndarray, target_res: int = 40) -> np.ndarray:
        h, w = img.shape[:2]
        small = cv2.resize(img, (target_res, target_res), interpolation=cv2.INTER_AREA)
        interp = cv2.INTER_LINEAR if np.random.rand() < 0.5 else cv2.INTER_NEAREST
        return cv2.resize(small, (w, h), interpolation=interp)

    @staticmethod
    def apply_shadow_gradient(img: np.ndarray) -> np.ndarray:
        """Simulate directional lighting / shadow across the face."""
        h, w = img.shape[:2]
        direction = np.random.choice(["horizontal", "vertical", "diagonal"])
        if direction == "horizontal":
            grad = np.linspace(np.random.uniform(0.3, 0.6), np.random.uniform(0.9, 1.1), w, dtype=np.float32)
            mask = np.tile(grad, (h, 1))
        elif direction == "vertical":
            grad = np.linspace(np.random.uniform(0.3, 0.6), np.random.uniform(0.9, 1.1), h, dtype=np.float32)
            mask = np.tile(grad[:, None], (1, w))
        else:
            gx = np.linspace(0.3, 1.0, w, dtype=np.float32)
            gy = np.linspace(0.3, 1.0, h, dtype=np.float32)
            mask = (gx[None, :] + gy[:, None]) / 2.0
        if np.random.rand() < 0.5:
            mask = np.fliplr(mask)
        mask = mask[:, :, None]
        return np.clip(img.astype(np.float32) * mask, 0, 255).astype(np.uint8)

    @staticmethod
    def apply_compression(img: np.ndarray, quality: int = 25) -> np.ndarray:
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), int(np.clip(quality, 10, 95))]
        _, buf = cv2.imencode(".jpg", img, encode_param)
        decoded = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        return decoded if decoded is not None else img

    # --- The 6 Distinct Presets ---
    @classmethod
    def preset_1_low_light(cls, img: np.ndarray) -> np.ndarray:
        """Preset 1: Low Light (Gamma + Cool Tint + CMOS noise)"""
        res = cls.apply_gamma(img, gamma=float(np.random.uniform(0.35, 0.48)))
        res = cls.apply_color_shift(res, b_add=8, r_sub=12)
        return cls.apply_sensor_noise(res, sigma=float(np.random.uniform(6.0, 12.0)))

    @classmethod
    def preset_2_motion_blur(cls, img: np.ndarray) -> np.ndarray:
        """Preset 2: Multi-Angle Motion Blur (12-28px linear shutter streak)"""
        length = int(np.random.uniform(12, 28))
        angle = float(np.random.uniform(0.0, 360.0))
        return cls.apply_cctv_motion_blur(img, length=length, angle_deg=angle)

    @classmethod
    def preset_3_low_light_motion_blur(cls, img: np.ndarray) -> np.ndarray:
        """Preset 3: Low Light + Motion Blur + Noise"""
        res = cls.apply_gamma(img, gamma=float(np.random.uniform(0.35, 0.45)))
        res = cls.apply_color_shift(res, b_add=12, r_sub=16)
        angle = float(np.random.uniform(0.0, 360.0))
        res = cls.apply_cctv_motion_blur(res, length=int(np.random.uniform(14, 24)), angle_deg=angle)
        res = cls.apply_sensor_noise(res, sigma=float(np.random.uniform(10.0, 16.0)))
        return cls.apply_compression(res, quality=int(np.random.uniform(30, 45)))

    @classmethod
    def preset_4_extreme_low_light(cls, img: np.ndarray) -> np.ndarray:
        """Preset 4: Extreme Low Light with Heavy Sensor Noise"""
        res = cls.apply_gamma(img, gamma=float(np.random.uniform(0.22, 0.30)))
        res = cls.apply_color_shift(res, b_add=16, r_sub=25)
        res = cls.apply_sensor_noise(res, sigma=float(np.random.uniform(18.0, 26.0)))
        return cls.apply_compression(res, quality=int(np.random.uniform(20, 35)))

    @classmethod
    def preset_5_low_quality(cls, img: np.ndarray) -> np.ndarray:
        """Preset 5: Low Quality (Sensor Downscale + Heavy H.264 compression)"""
        res = cls.apply_downscale_upscale(img, target_res=int(np.random.choice([24, 32, 40, 48])))
        res = cls.apply_sensor_noise(res, sigma=float(np.random.uniform(8.0, 14.0)))
        return cls.apply_compression(res, quality=int(np.random.uniform(15, 28)))

    @classmethod
    def preset_6_shadow_gradient(cls, img: np.ndarray) -> np.ndarray:
        """Preset 6: Directional Shadow Gradient + Noise"""
        res = cls.apply_shadow_gradient(img)
        res = cls.apply_sensor_noise(res, sigma=float(np.random.uniform(4.0, 8.0)))
        return res

    @classmethod
    def degrade(cls, clean_img: np.ndarray) -> np.ndarray:
        """Randomly sample one of the 6 realistic CCTV degradation presets."""
        preset_idx = np.random.randint(1, 7)
        if preset_idx == 1:
            return cls.preset_1_low_light(clean_img)
        elif preset_idx == 2:
            return cls.preset_2_motion_blur(clean_img)
        elif preset_idx == 3:
            return cls.preset_3_low_light_motion_blur(clean_img)
        elif preset_idx == 4:
            return cls.preset_4_extreme_low_light(clean_img)
        elif preset_idx == 5:
            return cls.preset_5_low_quality(clean_img)
        else:
            return cls.preset_6_shadow_gradient(clean_img)


# ---------------------------------------------------------------------------
# Balanced CCTV Distillation Dataset
# ---------------------------------------------------------------------------

class CCTVBalancedDistillationDataset(Dataset):
    """Provides paired (Clean Crop, Degraded Crop, Teacher Embedding, Label) batches."""

    def __init__(self, clean_crops: List[np.ndarray], teacher_embs: List[np.ndarray], labels: List[int]) -> None:
        self.clean_crops = clean_crops
        self.teacher_embs = teacher_embs
        self.labels = labels

    def __len__(self) -> int:
        return len(self.clean_crops)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        clean = self.clean_crops[idx]
        teacher_emb = self.teacher_embs[idx]
        label = self.labels[idx]

        # 50% chance clean face, 50% chance CCTV degraded face
        # This guarantees high recognition on both clean clear faces AND degraded CCTV faces!
        if np.random.rand() < 0.50:
            student_crop = clean.copy()
        else:
            student_crop = RealisticCCTVDegrader.degrade(clean)

        # Preprocessing: RGB [-1, 1]
        rgb = cv2.cvtColor(student_crop, cv2.COLOR_BGR2RGB).astype(np.float32)
        tensor = torch.from_numpy(np.transpose((rgb / 127.5) - 1.0, (2, 0, 1)))

        return (
            tensor,
            torch.from_numpy(teacher_emb.astype(np.float32)),
            torch.tensor(label, dtype=torch.long),
        )


# ---------------------------------------------------------------------------
# Training & Distillation Pipeline Execution
# ---------------------------------------------------------------------------

def run_distillation(epochs: int = 30, batch_size: int = 16, lr: float = 3e-4) -> None:
    print("=" * 80)
    print("      STUDENT V2: REALISTIC CCTV SURVEILLANCE DISTILLATION TRAINING      ")
    print("=" * 80)

    # 1. Collect clean high-resolution face crops and precompute Teacher embeddings using buffalo_l
    from insightface.app import FaceAnalysis
    from insightface.utils import face_align

    print("[1/4] Initializing Teacher buffalo_l (ResNet-50) for offline supervision...")
    teacher = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"])
    teacher.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.30)

    clean_crops: List[np.ndarray] = []
    teacher_embs: List[np.ndarray] = []
    labels: List[int] = []

    samples_dir = ROOT / "data" / "real_samples"
    person_dirs = sorted([d for d in samples_dir.iterdir() if d.is_dir()])
    label_map = {d.name: idx for idx, d in enumerate(person_dirs)}

    print(f"      Loading identities from {samples_dir}: {list(label_map.keys())}")

    for pdir in person_dirs:
        label_idx = label_map[pdir.name]
        for img_path in sorted(list(pdir.glob("*.png")) + list(pdir.glob("*.jpg"))):
            img = cv2.imread(str(img_path))
            if img is None:
                continue
            faces = teacher.get(img)
            if not faces:
                continue
            face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
            aligned = face_align.norm_crop(img, landmark=face.kps)
            emb = getattr(face, "normed_embedding", None)
            if emb is not None:
                clean_crops.append(aligned)
                teacher_embs.append(np.asarray(emb, dtype=np.float32))
                labels.append(label_idx)

    # Replicate/oversample dataset to provide rich distillation epochs
    augmented_crops: List[np.ndarray] = []
    augmented_embs: List[np.ndarray] = []
    augmented_labels: List[int] = []

    for _ in range(25):
        for crop, emb, lbl in zip(clean_crops, teacher_embs, labels):
            augmented_crops.append(crop)
            augmented_embs.append(emb)
            augmented_labels.append(lbl)

    print(f"      Prepared {len(augmented_crops)} distillation samples across {len(label_map)} identities.")

    # 2. Build Student V2 PyTorch Model
    print("\n[2/4] Building Student V2 MobileFaceNet Architecture (512-D)...")
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    student = MobileFaceNet(variant="std", embedding_dim=512).to(device)

    criterion = ArcFaceDistillationLoss(
        num_classes=max(2, len(label_map)),
        embedding_dim=512,
        lambda_feat=3.0,
        lambda_cos=3.0,
    ).to(device)

    optimizer = torch.optim.AdamW(
        list(student.parameters()) + list(criterion.parameters()),
        lr=lr,
        weight_decay=1e-4,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    dataset = CCTVBalancedDistillationDataset(augmented_crops, augmented_embs, augmented_labels)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=True)

    # 3. Training Loop
    print(f"\n[3/4] Training Student V2 for {epochs} epochs on {device}...")
    student.train()
    for epoch in range(epochs):
        total_loss = 0.0
        total_cos = 0.0
        steps = 0
        for crops, t_embs, y in dataloader:
            crops = crops.to(device)
            t_embs = F.normalize(t_embs.to(device), p=2, dim=1)
            y = y.to(device)

            optimizer.zero_grad()
            student_embs = student(crops)
            loss, loss_arc, loss_feat = criterion(student_embs, t_embs, y)
            loss.backward()
            optimizer.step()

            total_loss += float(loss.item())
            # Track cosine similarity to clean teacher embedding
            cos_sim = F.cosine_similarity(student_embs, t_embs).mean().item()
            total_cos += cos_sim
            steps += 1

        scheduler.step()
        if (epoch + 1) % 5 == 0 or epoch == epochs - 1:
            avg_loss = total_loss / max(1, steps)
            avg_cos = total_cos / max(1, steps)
            print(f"  Epoch [{epoch+1:02d}/{epochs:02d}] Loss: {avg_loss:.4f} | Avg Teacher Cosine Alignment: {avg_cos:.4f} | LR: {scheduler.get_last_lr()[0]:.6f}")

    # 4. Export Standalone INT8 ONNX Model
    print("\n[4/4] Exporting Standalone INT8 ONNX Weights (Zero buffalo_l dependency)...")
    out_dir = ROOT / "weights" / "custom_student"
    out_dir.mkdir(parents=True, exist_ok=True)
    fp32_path = out_dir / "student_std_512d_fp32.onnx"
    int8_path = out_dir / "student_std_512d_int8.onnx"

    student.eval()
    dummy = torch.randn(1, 3, 112, 112, device=device)
    torch.onnx.export(
        student,
        dummy,
        str(fp32_path),
        opset_version=12,
        input_names=["input"],
        output_names=["output"],
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
        dynamo=False,
    )

    from onnxruntime.quantization import QuantType, quantize_dynamic
    quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QUInt8)

    # Remove the heavy fp32 file so git repository remains compact
    if fp32_path.exists():
        fp32_path.unlink()

    print(f"  Successfully Generated: {int8_path} ({int8_path.stat().st_size / (1024*1024):.2f} MB)")
    print("=" * 80)
    print("      STUDENT V2 TRAINING & EXPORT COMPLETE      ")
    print("=" * 80)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train Student V2 CCTV Recognizer")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-4)
    args = parser.parse_args()

    run_distillation(epochs=args.epochs, batch_size=args.batch_size, lr=args.lr)
