#!/usr/bin/env python3
"""Surveillance Face Recognition Training Script for QMUL-SurvFace & SCface.

Supports training lightweight student models on:
1. QMUL-SurvFace benchmark (463,507 CCTV face images, 15,573 identities)
2. SCface surveillance benchmark (4,160 multi-camera surveillance faces, 130 subjects)
3. Custom Surveillance Directories

Outputs standalone INT8 ONNX models optimized for edge CCTV surveillance.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.utils.data import DataLoader, Dataset

# Set up project path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from onnxruntime.quantization import QuantType, quantize_dynamic
from python_recognizer.custom_pipeline import CustomONNXFacePipeline
from python_recognizer.train_student import MobileFaceNet


class QMULSurvFaceDataset(Dataset):
    """Dataset loader for QMUL-SurvFace benchmark."""

    def __init__(self, root_dir: Path, target_size: tuple[int, int] = (112, 112)) -> None:
        self.root_dir = Path(root_dir)
        self.target_size = target_size
        self.samples: list[tuple[Path, int]] = []
        self.identity_map: dict[str, int] = {}

        if not self.root_dir.exists():
            raise FileNotFoundError(f"QMUL-SurvFace directory not found: {self.root_dir}")

        # Scan for image files recursively across all subdirectories
        image_extensions = {".jpg", ".jpeg", ".png", ".bmp"}
        for img_path in sorted(self.root_dir.glob("**/*.*")):
            if img_path.suffix.lower() in image_extensions:
                stem = img_path.stem
                id_name = stem.split("_")[0]
                if id_name and id_name.isdigit():
                    if id_name not in self.identity_map:
                        self.identity_map[id_name] = len(self.identity_map)
                    id_idx = self.identity_map[id_name]
                    self.samples.append((img_path, id_idx))

        print(f"Loaded QMUL-SurvFace: {len(self.samples)} images across {len(self.identity_map)} identities.")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        img_path, label = self.samples[idx]
        img = cv2.imread(str(img_path))
        if img is None:
            # Return dummy tensor if corrupted
            return torch.zeros((3, self.target_size[1], self.target_size[0]), dtype=torch.float32), label

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(img_rgb, self.target_size, interpolation=cv2.INTER_AREA)
        # Normalize to [-1.0, 1.0] standard ArcFace format
        normalized = (resized.astype(np.float32) - 127.5) / 127.5
        tensor = torch.from_numpy(normalized).permute(2, 0, 1).contiguous()
        return tensor, label


class SCfaceDataset(Dataset):
    """Dataset loader for SCface (Surveillance Cameras Face Database)."""

    def __init__(self, root_dir: Path, target_size: tuple[int, int] = (112, 112)) -> None:
        self.root_dir = Path(root_dir)
        self.target_size = target_size
        self.samples: list[tuple[Path, int]] = []
        self.identity_map: dict[str, int] = {}

        if not self.root_dir.exists():
            raise FileNotFoundError(f"SCface directory not found: {self.root_dir}")

        image_extensions = {".jpg", ".jpeg", ".png", ".bmp"}

        # SCface typically has camera folders (e.g. cam1_1, cam2_1, mugshot) with subject files: 001_cam1_1.jpg
        for img_path in sorted(self.root_dir.glob("**/*.*")):
            if img_path.suffix.lower() in image_extensions:
                # Extract 3-digit subject ID (e.g., '001', '042')
                stem = img_path.stem
                subject_id = stem.split("_")[0]
                if subject_id.isdigit():
                    if subject_id not in self.identity_map:
                        self.identity_map[subject_id] = len(self.identity_map)
                    id_idx = self.identity_map[subject_id]
                    self.samples.append((img_path, id_idx))

        print(f"Loaded SCface: {len(self.samples)} images across {len(self.identity_map)} identities.")

    def __len__(self) -> int:
        return len(self.samples)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        img_path, label = self.samples[idx]
        img = cv2.imread(str(img_path))
        if img is None:
            return torch.zeros((3, self.target_size[1], self.target_size[0]), dtype=torch.float32), label

        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(img_rgb, self.target_size, interpolation=cv2.INTER_AREA)
        normalized = (resized.astype(np.float32) - 127.5) / 127.5
        tensor = torch.from_numpy(normalized).permute(2, 0, 1).contiguous()
        return tensor, label


class ArcMarginProduct(nn.Module):
    """ArcFace Angular Margin Loss Head for deep metric learning."""

    def __init__(self, in_features: int, out_features: int, s: float = 30.0, m: float = 0.50) -> None:
        super().__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.s = s
        self.m = m
        self.weight = nn.Parameter(torch.FloatTensor(out_features, in_features))
        nn.init.xavier_uniform_(self.weight)

        self.cos_m = np.cos(m)
        self.sin_m = np.sin(m)
        self.th = np.cos(np.pi - m)
        self.mm = np.sin(np.pi - m) * m

    def forward(self, input_features: torch.Tensor, label: torch.Tensor) -> torch.Tensor:
        cosine = F.linear(F.normalize(input_features), F.normalize(self.weight))
        sine = torch.sqrt(torch.clamp(1.0 - torch.pow(cosine, 2), 1e-7, 1.0))
        phi = cosine * self.cos_m - sine * self.sin_m
        phi = torch.where(cosine > self.th, phi, cosine - self.mm)

        one_hot = torch.zeros(cosine.size(), device=input_features.device)
        one_hot.scatter_(1, label.view(-1, 1).long(), 1.0)
        output = (one_hot * phi) + ((1.0 - one_hot) * cosine)
        output *= self.s
        return output


def train_surveillance_network(
    dataset: Dataset,
    output_onnx: Path,
    epochs: int = 30,
    batch_size: int = 32,
    lr: float = 1e-3,
    embedding_dim: int = 512,
    device_name: str = "auto",
) -> Path:
    """Train MobileFaceNet on surveillance dataset with ArcFace Loss."""
    if device_name == "auto":
        device = torch.device("mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu"))
    else:
        device = torch.device(device_name)

    print(f"\n================================================================================")
    print(f"   TRAINING SURVEILLANCE STUDENT ON {device.type.upper()} ({len(dataset)} SAMPLES)")
    print(f"================================================================================")

    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True, drop_last=True, num_workers=0)
    num_classes = len(getattr(dataset, "identity_map", {})) or 100

    model = MobileFaceNet(variant="std", embedding_dim=embedding_dim).to(device)
    metric_head = ArcMarginProduct(in_features=embedding_dim, out_features=num_classes, s=32.0, m=0.45).to(device)
    criterion = nn.CrossEntropyLoss()

    optimizer = torch.optim.AdamW(
        list(model.parameters()) + list(metric_head.parameters()),
        lr=lr,
        weight_decay=1e-4,
    )
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    model.train()
    metric_head.train()

    for epoch in range(1, epochs + 1):
        running_loss = 0.0
        correct = 0
        total = 0

        for images, labels in loader:
            images = images.to(device)
            labels = labels.to(device)

            optimizer.zero_grad()
            embeddings = model(images)
            outputs = metric_head(embeddings, labels)
            loss = criterion(outputs, labels)

            loss.backward()
            optimizer.step()

            running_loss += loss.item() * images.size(0)
            _, predicted = outputs.max(1)
            total += labels.size(0)
            correct += predicted.eq(labels).sum().item()

        scheduler.step()
        epoch_loss = running_loss / max(1, total)
        epoch_acc = (100.0 * correct) / max(1, total)
        current_lr = scheduler.get_last_lr()[0]

        if epoch % 5 == 0 or epoch == epochs or epoch == 1:
            print(f"  Epoch [{epoch:02d}/{epochs:02d}] Loss: {epoch_loss:.4f} | Accuracy: {epoch_acc:.2f}% | LR: {current_lr:.6f}")

    # Export to ONNX
    output_onnx.parent.mkdir(parents=True, exist_ok=True)
    model.eval()
    dummy_input = torch.randn(1, 3, 112, 112, device=device)
    raw_onnx = output_onnx.with_name(output_onnx.stem + "_fp32.onnx")

    print(f"\nExporting FP32 ONNX to {raw_onnx}...")
    torch.onnx.export(
        model,
        dummy_input,
        str(raw_onnx),
        input_names=["input.1"],
        output_names=["683"],
        dynamic_axes={"input.1": {0: "batch_size"}, "683": {0: "batch_size"}},
        opset_version=18,
    )

    # Dynamic INT8 Quantization for Edge CCTV CPU performance
    print(f"Quantizing to Standalone INT8 ONNX: {output_onnx}...")
    quantize_dynamic(str(raw_onnx), str(output_onnx), weight_type=QuantType.QInt8)
    size_mb = output_onnx.stat().st_size / (1024 * 1024)
    print(f"Export Complete: {output_onnx} ({size_mb:.2f} MB)")
    return output_onnx


def main() -> None:
    parser = argparse.ArgumentParser(description="Train Face Recognition on QMUL-SurvFace or SCface")
    parser.add_argument("--qmul_dir", type=str, default=None, help="Path to QMUL-SurvFace extracted folder")
    parser.add_argument("--scface_dir", type=str, default=None, help="Path to SCface extracted folder")
    parser.add_argument("--epochs", type=int, default=30, help="Number of training epochs")
    parser.add_argument("--batch_size", type=int, default=32, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--output", type=str, default="weights/custom_student/survface_int8.onnx", help="Output INT8 ONNX path")
    args = parser.parse_args()

    if not args.qmul_dir and not args.scface_dir:
        print("Usage error: Please specify either --qmul_dir <path> or --scface_dir <path>")
        print("\nExamples:")
        print("  python scripts/train_survface.py --qmul_dir /path/to/QMUL-SurvFace")
        print("  python scripts/train_survface.py --scface_dir /path/to/SCface")
        sys.exit(1)

    if args.qmul_dir:
        dataset = QMULSurvFaceDataset(Path(args.qmul_dir))
    else:
        dataset = SCfaceDataset(Path(args.scface_dir))

    output_path = Path(args.output)
    train_surveillance_network(
        dataset=dataset,
        output_onnx=output_path,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
    )


if __name__ == "__main__":
    main()
