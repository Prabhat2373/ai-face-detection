"""Train the custom recognizer from labeled CCTV crops and buffalo_l teacher embeddings."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from insightface.app import FaceAnalysis

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python_recognizer.train_student import ArcFaceDistillationLoss, CCTVAugmenter, MobileFaceNet


DATASET = ROOT / "data" / "real_samples"
OUTPUT = ROOT / "weights" / "custom_student"
TEACHER_ROOT = Path.home() / ".cache" / "insightface"


def collect_teacher_samples() -> tuple[list[np.ndarray], list[np.ndarray], list[str]]:
    teacher = FaceAnalysis(name="buffalo_l", root=str(TEACHER_ROOT), providers=["CPUExecutionProvider"], allowed_modules=["detection", "recognition"])
    teacher.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.30)
    images, embeddings, labels = [], [], []
    for person_dir in sorted(DATASET.iterdir()):
        if not person_dir.is_dir():
            continue
        for image_path in sorted(person_dir.glob("*")):
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            faces = teacher.get(image)
            if not faces:
                continue
            face = max(faces, key=lambda item: float(item.bbox[2] - item.bbox[0]) * float(item.bbox[3] - item.bbox[1]))
            x1, y1, x2, y2 = [int(v) for v in face.bbox]
            pad_x, pad_y = int((x2 - x1) * 0.20), int((y2 - y1) * 0.20)
            crop = image[max(0, y1 - pad_y):min(image.shape[0], y2 + pad_y), max(0, x1 - pad_x):min(image.shape[1], x2 + pad_x)]
            if crop.size == 0 or getattr(face, "normed_embedding", None) is None:
                continue
            images.append(cv2.resize(crop, (112, 112)))
            embeddings.append(np.asarray(face.normed_embedding, dtype=np.float32))
            labels.append(person_dir.name)
    if len(set(labels)) < 2:
        raise RuntimeError("At least two labeled identities are required")
    print(f"Collected {len(images)} teacher-labeled crops across {sorted(set(labels))}")
    return images, embeddings, labels


def train() -> None:
    images, teacher_embeddings, labels = collect_teacher_samples()
    label_names = sorted(set(labels))
    label_ids = {label: index for index, label in enumerate(label_names)}
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MobileFaceNet(variant="std", embedding_dim=512).to(device)
    criterion = ArcFaceDistillationLoss(num_classes=len(label_names), embedding_dim=512, lambda_feat=2.0, lambda_cos=2.0).to(device)
    optimizer = torch.optim.AdamW(list(model.parameters()) + list(criterion.parameters()), lr=3e-4, weight_decay=1e-4)
    rng = np.random.default_rng(42)
    model.train()
    for epoch in range(40):
        order = rng.permutation(len(images))
        total = 0.0
        for start in range(0, len(order), 8):
            batch = order[start:start + 8]
            crops = []
            for index in batch:
                crop = images[index]
                crop = CCTVAugmenter.augment(crop) if rng.random() < 0.7 else crop
                rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)
                crops.append(np.transpose((rgb / 127.5) - 1.0, (2, 0, 1)))
            x = torch.from_numpy(np.asarray(crops, dtype=np.float32)).to(device)
            t = F.normalize(torch.from_numpy(np.asarray([teacher_embeddings[i] for i in batch], dtype=np.float32)).to(device), p=2, dim=1)
            y = torch.tensor([label_ids[labels[i]] for i in batch], dtype=torch.long, device=device)
            optimizer.zero_grad()
            student = model(x)
            loss, _, _ = criterion(student, t, y)
            loss.backward()
            optimizer.step()
            total += float(loss.item())
        if epoch % 5 == 4:
            print(f"epoch {epoch + 1}/40 loss={total:.4f}")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    pt_path = OUTPUT / "student_std_512d.pt"
    fp32_path = OUTPUT / "student_std_512d_fp32.onnx"
    int8_path = OUTPUT / "student_std_512d_int8.onnx"
    torch.save(model.eval().state_dict(), pt_path)
    dummy = torch.randn(1, 3, 112, 112, device=device)
    torch.onnx.export(model.eval(), dummy, str(fp32_path), opset_version=12, input_names=["input"], output_names=["output"], dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}}, dynamo=False)
    from onnxruntime.quantization import QuantType, quantize_dynamic
    quantize_dynamic(str(fp32_path), str(int8_path), weight_type=QuantType.QUInt8)
    print(f"Exported {fp32_path} and {int8_path}")


if __name__ == "__main__":
    train()
