"""Unit Tests for Custom Model Distillation, Augmentations, Loss Functions, and Benchmarks."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from python_recognizer.evaluator import CCTVValidator, OpenSetEvaluator, QuantizationBenchmarker
from python_recognizer.train_student import (
    TORCH_AVAILABLE,
    CCTVAugmenter,
    OpenSetDatasetGenerator,
    StudentTrainer,
)

if TORCH_AVAILABLE:
    import torch
    import torch.nn.functional as F
    from python_recognizer.train_student import ArcFaceDistillationLoss, MobileFaceNet


class TestCustomModelDistillation(unittest.TestCase):

    def setUp(self) -> None:
        self.test_dir = Path(tempfile.mkdtemp(prefix="test_custom_model_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_cctv_augmentation(self) -> None:
        img = np.zeros((112, 112, 3), dtype=np.uint8)
        img[30:80, 30:80] = (200, 200, 200)
        aug_img = CCTVAugmenter.augment(img)
        self.assertEqual(aug_img.shape, (112, 112, 3))

    def test_02_dataset_generator(self) -> None:
        gen = OpenSetDatasetGenerator(num_identities=3, samples_per_identity=2, target_dir=str(self.test_dir / "ds"))
        ds_path = gen.generate()
        identities = [d for d in ds_path.iterdir() if d.is_dir()]
        self.assertEqual(len(identities), 3)

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch required")
    def test_03_mobilefacenet_factory(self) -> None:
        for variant in ["tiny", "std", "large"]:
            for dim in [128, 256, 512]:
                model = MobileFaceNet(variant=variant, embedding_dim=dim)
                dummy = torch.randn(2, 3, 112, 112)
                out = model(dummy)
                self.assertEqual(out.shape, (2, dim))

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch required")
    def test_04_distillation_loss(self) -> None:
        criterion = ArcFaceDistillationLoss(num_classes=5, embedding_dim=512)
        student_emb = F.normalize(torch.randn(4, 512), p=2, dim=1) if TORCH_AVAILABLE else None
        teacher_emb = F.normalize(torch.randn(4, 512), p=2, dim=1) if TORCH_AVAILABLE else None
        labels = torch.tensor([0, 1, 2, 3])

        total_loss, loss_arc, loss_feat = criterion(student_emb, teacher_emb, labels)
        self.assertTrue(float(total_loss.item()) > 0.0)

    @unittest.skipUnless(TORCH_AVAILABLE, "PyTorch required")
    def test_05_student_training_and_export(self) -> None:
        gen = OpenSetDatasetGenerator(num_identities=3, samples_per_identity=2, target_dir=str(self.test_dir / "ds_train"))
        ds_path = gen.generate()

        out_dir = self.test_dir / "weights"
        trainer = StudentTrainer(dataset_dir=ds_path, variant="tiny", embedding_dim=128, epochs=1, batch_size=2)
        res = trainer.train_and_export(out_dir)

        self.assertEqual(res["variant"], "tiny")
        self.assertEqual(res["embedding_dim"], 128)
        self.assertTrue(os.path.exists(res["onnx_results"]["fp32"]))

    def test_06_openset_evaluator(self) -> None:
        genuine = [0.8, 0.85, 0.9, 0.75]
        imposter = [0.1, 0.15, 0.2, 0.25]
        eval_res = OpenSetEvaluator.evaluate(genuine, imposter)
        self.assertIn("eer", eval_res)
        self.assertIn("optimal_threshold", eval_res)
        self.assertLess(eval_res["eer"], 0.1)


if __name__ == "__main__":
    unittest.main()
