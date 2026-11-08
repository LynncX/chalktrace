"""验证标注约束、真实视频解码和策略回放统计；不加载 OCR 或人体模型。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import yaml

from evaluation.evaluate_gate import evaluate, validate_cases
from workbench.build import build


class GatePairEvaluationTests(unittest.TestCase):
    def document(self):
        return {"video": "clip.avi", "config": {"gate_mode": "change", "cooldown_s": 0},
                "description": "假定参考图已 OCR；只是组件回放。", "missing_real_categories": ["erase"],
                "cases": [{"id": "stable", "category": "static", "expected_fire": False,
                           "reference_s": 0, "target_s": .5, "roi": [0, 0, 96, 72], "note": "静态"},
                          {"id": "new", "category": "added", "expected_fire": True,
                           "reference_s": 0, "target_s": 1.5, "roi": [0, 0, 96, 72], "note": "新增"}]}

    def test_rejects_conflicting_labels_duplicate_ids_and_invalid_times(self):
        for field, value in (("category", "unknown"), ("expected_fire", "false"),
                             ("expected_fire", True), ("target_s", float("nan")),
                             ("reference_s", 2), ("id", "../escape"), ("roi", [0, 0, 1, 10])):
            document = self.document()
            document["cases"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_cases(document)
        document = self.document()
        document["cases"][1]["id"] = "stable"
        with self.assertRaises(ValueError):
            validate_cases(document)

    def test_real_decode_records_actual_timestamps_and_no_ocr_cost_claim(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = cv2.VideoWriter(str(root / "clip.avi"), cv2.VideoWriter_fourcc(*"MJPG"), 10, (96, 72))
            self.assertTrue(video.isOpened())
            for index in range(20):
                image = np.full((72, 96, 3), 220, dtype="uint8")
                if index >= 10:
                    cv2.rectangle(image, (20, 20), (70, 45), (0, 0, 0), -1)
                video.write(image)
            video.release()
            annotations = root / "cases.yaml"
            annotations.write_text(yaml.safe_dump(self.document(), allow_unicode=True))
            with patch("evaluation.evaluate_gate.EXPERIMENTS", root / "experiments"):
                summary, out = evaluate(annotations, "check")
                with self.assertRaises(FileExistsError):
                    evaluate(annotations, "check")
            self.assertEqual(summary["passed"], 2)
            self.assertEqual(summary["actual_ocr_calls"], 0)
            self.assertEqual(summary["kind"], "component_policy_replay")
            self.assertEqual(summary["records"][1]["frame"], 15)
            self.assertEqual(summary["records"][1]["ts"], 1.5)
            self.assertEqual(summary["missing_real_categories"], ["erase"])
            self.assertEqual(json.loads((out / "annotations.json").read_text())["cases"], self.document()["cases"])
            info = build(str(out), assets_mode="inline")
            page = info["path"].read_text()
            self.assertIn("假定参考图已 OCR", page)
            self.assertIn("参考帧", page)
            self.assertIn("候选帧与策略决策", page)


if __name__ == "__main__":
    unittest.main()
