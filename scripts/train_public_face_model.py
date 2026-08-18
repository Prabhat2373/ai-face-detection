"""Train the custom MobileFaceNet recognizer from a public face dataset.

Expected layout:
    DATASET_ROOT/<identity>/<image files>

Training uses buffalo_l only in the training environment to provide teacher
embeddings. Client/runtime packages never need buffalo_l or InsightFace.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from insightface.app import FaceAnalysis
from torch.utils.data import DataLoader, Dataset

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from python_recognizer.train_student import ArcFaceDistillationLoss, CCTVAugmenter, MobileFaceNet  # noqa: E402


class FaceRecord:
    def __init__(self, crop: np.ndarray, teacher_embedding: np.ndarray, label: int) -> None:
        self.crop = crop
        self.teacher_embedding = teacher_embedding
        self.label = label


class PublicFaceDataset(Dataset):
    def __init__(self, records: list[FaceRecord], train: bool) -> None:
        self.records = records
        self.train = train

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int):
        record = self.records[index]
        crop = record.crop.copy()
        if self.train:
            crop = CCTVAugmenter.augment(crop)
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32)
        tensor = torch.from_numpy(np.transpose((rgb / 127.5) - 1.0, (2, 0, 1)))
        teacher = torch.from_numpy(record.teacher_embedding.astype(np.float32))
        return tensor, teacher, record.label


def crop_face(image: np.ndarray, face: object) -> np.ndarray | None:
    box = np.asarray(getattr(face, "bbox", []), dtype=np.int32).reshape(-1)
    if box.size < 4:
        return None
    x1, y1, x2, y2 = [int(v) for v in box[:4]]
    w, h = max(1, x2 - x1), max(1, y2 - y1)
    px, py = int(w * 0.20), int(h * 0.20)
    crop = image[max(0, y1 - py):min(image.shape[0], y2 + py), max(0, x1 - px):min(image.shape[1], x2 + px)]
    return cv2.resize(crop, (112, 112), interpolation=cv2.INTER_AREA) if crop.size else None


def prepare_records(dataset_root: Path, teacher: FaceAnalysis, max_identities: int, min_images: int) -> tuple[list[FaceRecord], list[str]]:
    identity_dirs = sorted(path for path in dataset_root.iterdir() if path.is_dir())
    identity_dirs = [path for path in identity_dirs if sum(1 for _ in path.glob("*")) >= min_images][:max_identities]
    names = [path.name for path in identity_dirs]
    records: list[FaceRecord] = []
    for label, identity_dir in enumerate(identity_dirs):
        files = [path for path in identity_dir.glob("*") if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}]
        for image_path in files:
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            faces = teacher.get(image)
            if not faces:
                continue
            face = max(faces, key=lambda item: float(item.bbox[2] - item.bbox[0]) * float(item.bbox[3] - item.bbox[1]))
            crop = crop_face(image, face)
            embedding = getattr(face, "normed_embedding", None)
            if crop is not None and embedding is not None:
                records.append(FaceRecord(crop, np.asarray(embedding, dtype=np.float32), label))
        if (label + 1) % 100 == 0:
            print(f"prepared {label + 1}/{len(identity_dirs)} identities")
    return records, names


def split_records(records: list[FaceRecord], validation_ratio: float, seed: int) -> tuple[list[FaceRecord], list[FaceRecord]]:
    rng = random.Random(seed)
    by_label: dict[int, list[FaceRecord]] = {}
    for record in records:
        by_label.setdefault(record.label, []).append(record)
    train, validation = [], []
    for items in by_label.values():
        rng.shuffle(items)
        count = max(1, int(len(items) * validation_ratio)) if len(items) > 1 else 0
        validation.extend(items[:count])
        train.extend(items[count:])
    return train, validation


@torch.no_grad()
def evaluate(model: torch.nn.Module, loader: DataLoader, device: torch.device) -> float:
    model.eval()
    embeddings, labels = [], []
    for crops, _, batch_labels in loader:
        embeddings.append(model(crops.to(device)).cpu())
        labels.extend(batch_labels.tolist())
    if not embeddings:
        return 0.0
    vectors = torch.cat(embeddings)
    same, total = 0, 0
    for i in range(len(vectors)):
        for j in range(i + 1, len(vectors)):
            if labels[i] == labels[j]:
                same += float(torch.dot(vectors[i], vectors[j]) >= 0.45)
                total += 1
    return same / max(1, total)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True, help="Identity-folder public dataset")
    parser.add_argument("--output", type=Path, default=ROOT / "weights/custom_student")
    parser.add_argument("--max-identities", type=int, default=10000)
    parser.add_argument("--min-images", type=int, default=5)
    parser.add_argument("--epochs", type=int, default=25)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)

    teacher = FaceAnalysis(name="buffalo_l", root=str(Path.home() / ".cache/insightface"), providers=["CPUExecutionProvider"], allowed_modules=["detection", "recognition"])
    teacher.prepare(ctx_id=-1, det_size=(640, 640), det_thresh=0.30)
    records, identity_names = prepare_records(args.dataset, teacher, args.max_identities, args.min_images)
    if len(identity_names) < 2 or len(records) < 100:
        raise RuntimeError("Need at least 2 identities and 100 usable detected face images")
    train_records, val_records = split_records(records, 0.15, args.seed)
    train_loader = DataLoader(PublicFaceDataset(train_records, True), batch_size=args.batch_size, shuffle=True, num_workers=0, drop_last=True)
    val_loader = DataLoader(PublicFaceDataset(val_records, False), batch_size=args.batch_size, shuffle=False, num_workers=0)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = MobileFaceNet("std", 512).to(device)
    criterion = ArcFaceDistillationLoss(len(identity_names), 512, margin=0.5, scale=64.0, lambda_feat=1.0, lambda_cos=2.0).to(device)
    optimizer = torch.optim.AdamW(list(model.parameters()) + list(criterion.parameters()), lr=3e-4, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=args.epochs, eta_min=1e-6)
    best_score, best_state = -1.0, None
    for epoch in range(args.epochs):
        model.train()
        running = 0.0
        for crops, teachers, labels in train_loader:
            optimizer.zero_grad(set_to_none=True)
            student = model(crops.to(device))
            loss, _, _ = criterion(student, F.normalize(teachers.to(device), p=2, dim=1), labels.to(device))
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            running += float(loss.item())
        scheduler.step()
        score = evaluate(model, val_loader, device)
        print(f"epoch {epoch + 1}/{args.epochs} loss={running / max(1, len(train_loader)):.4f} val_same_rate={score:.4f}")
        if score > best_score:
            best_score = score
            best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}

    if best_state is None:
        raise RuntimeError("Training produced no checkpoint")
    model.load_state_dict(best_state)
    args.output.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), args.output / "student_std_512d.pt")
    dummy = torch.randn(1, 3, 112, 112, device=device)
    fp32 = args.output / "student_std_512d_fp32.onnx"
    int8 = args.output / "student_std_512d_int8.onnx"
    torch.onnx.export(model.eval(), dummy, str(fp32), opset_version=12, input_names=["input"], output_names=["output"], dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}}, dynamo=False)
    from onnxruntime.quantization import QuantType, quantize_dynamic
    quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QUInt8)
    (args.output / "training_report.json").write_text(json.dumps({"identities": len(identity_names), "records": len(records), "bestValidationSameRate": best_score}, indent=2), encoding="utf-8")
    print(f"Exported custom model to {args.output}; re-register all local employees before use.")


if __name__ == "__main__":
    main()
