"""无网络测试：真实视频读写 + 注入 OCR，验证编排、坐标证据及失败状态。"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from cv_engine.config import PipelineConfig
from cv_engine.contracts import OcrBox
from cv_engine.pipeline import run
from cv_engine.schema import validate_manifest
from cv_engine.stages.s02_board import locate_board
from cv_engine.writer import RunWriter
from workbench.build import build


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.video = self.root / "sample.avi"
        encoder = cv2.VideoWriter(str(self.video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (96, 72))
        self.assertTrue(encoder.isOpened())
        for index in range(20):
            frame = np.full((72, 96, 3), 220, dtype=np.uint8)
            cv2.putText(frame, str(index), (10, 30), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 0, 0), 1)
            encoder.write(frame)
        encoder.release()

    def test_video_to_manifest_and_workbench_with_source_coordinates(self):
        created = []

        class FakeEngine:
            def __init__(self, config):
                created.append(self)

            def recognize(self, image, *, frame, ts, call):
                return [OcrBox(text="原文 ``` <tag>", poly=[[10, 10], [30, 10], [30, 20], [10, 20]],
                               score=.8, frame=frame, ts=ts, ocr_call=call)]

        writer = RunWriter("test", root=self.root / "run")
        config = PipelineConfig(start_s=.2, end_s=1.3, sample_interval_s=.5,
                                max_frames=9, roi=[8, 6, 64, 48])
        result = run(self.video, config, writer, engine_factory=FakeEngine)
        manifest = json.loads(result["path"].read_text())
        self.assertEqual(validate_manifest(manifest), [])
        self.assertEqual(manifest["status"], "done")
        self.assertEqual(manifest["stages"]["06"]["metrics"]["calls"], 3)
        self.assertEqual(len(created), 1)
        for no in ("03", "04"):
            self.assertEqual(manifest["stages"][no]["status"], "pending")
        self.assertEqual(len(manifest["items"]), 1)
        self.assertEqual(manifest["stages"]["07"]["status"], "done")
        self.assertEqual(manifest["items"][0]["first_seen_sec"], .2)
        self.assertEqual(manifest["items"][0]["last_seen_sec"], 1.2)
        history = json.loads((writer.root / manifest["items"][0]["evidence"]["history"]).read_text())
        self.assertEqual(len(history["observations"]), 3)
        self.assertEqual((writer.root / "08_notes/notes.txt").read_text().count("原文"), 1)
        boxes = json.loads((writer.root / "06_ocr/boxes.json").read_text())
        self.assertEqual([box["frame"] for box in boxes], [2, 7, 12])
        self.assertEqual([box["ts"] for box in boxes], [.2, .7, 1.2])
        np.testing.assert_allclose(boxes[0]["source_poly"][0], [18, 16], atol=1e-4)
        for entry in manifest["files"]:
            self.assertTrue((writer.root / entry["path"]).is_file(), entry)
        html = build(str(writer.root), assets_mode="inline")
        self.assertTrue(html["path"].is_file())
        page = html["path"].read_text()
        self.assertIn("白板区域核验", page)
        self.assertIn("人工矩形 ROI", page)
        self.assertIn("原图标定 · 边界与四角", page)
        self.assertIn("裁剪结果", page)
        calibration = json.loads((writer.root / "02_board/calibration.json").read_text())
        self.assertTrue((writer.root / calibration[0]["overlay_path"]).is_file())
        self.assertTrue((writer.root / calibration[0]["source_path"]).is_file())
        self.assertIn("原文", (writer.root / "08_notes/notes.txt").read_text())

    def test_model_failure_marks_run_and_stage(self):
        def fail(config):
            raise RuntimeError("模型加载失败")

        writer = RunWriter("failure", root=self.root / "failed")
        with self.assertRaisesRegex(RuntimeError, "模型加载失败"):
            run(self.video, PipelineConfig(max_frames=1), writer, engine_factory=fail)
        manifest = json.loads((writer.root / "manifest.json").read_text())
        self.assertEqual(manifest["status"], "failed")
        self.assertIn("模型加载失败", manifest["stages"]["06"]["note"])

    def test_no_usable_frames_fails_before_loading_model(self):
        factory = unittest.mock.Mock()
        writer = RunWriter("empty", root=self.root / "empty")
        with self.assertRaisesRegex(ValueError, "无可用采样帧"):
            run(self.video, PipelineConfig(max_frames=1, blur_min=1e12), writer, engine_factory=factory)
        factory.assert_not_called()
        self.assertEqual(writer.manifest.status, "failed")

    def test_empty_ocr_result_is_a_valid_run_with_warning(self):
        class EmptyEngine:
            def __init__(self, config):
                pass

            def recognize(self, image, **kwargs):
                return []

        writer = RunWriter("no_text", root=self.root / "no_text")
        result = run(self.video, PipelineConfig(max_frames=1), writer, engine_factory=EmptyEngine)
        self.assertEqual(result["errors"], [])
        self.assertEqual(writer.manifest.stage("06").metrics["boxes"], 0)
        self.assertIsNone(writer.manifest.stage("06").metrics["score"])
        self.assertTrue(any("没有识别出文字" in msg for msg in result["warnings"]))

    def test_perspective_maps_corners_and_rejects_invalid_regions(self):
        image = np.zeros((72, 96, 3), dtype=np.uint8)
        points = [[8, 6], [80, 10], [85, 60], [5, 65]]
        board, _, meta = locate_board(image, PipelineConfig(corners=points))
        mapped = cv2.perspectiveTransform(np.float32([points]), np.array(meta["source_to_board"]))[0]
        np.testing.assert_allclose(mapped, [[0, 0], [board.shape[1]-1, 0],
                                   [board.shape[1]-1, board.shape[0]-1], [0, board.shape[0]-1]], atol=1e-4)
        for config in (PipelineConfig(roi=[90, 0, 20, 20]),
                       PipelineConfig(corners=[[0, 0]] * 4),
                       PipelineConfig(corners=[[0, 0], [0, 50], [50, 50], [50, 0]])):
            with self.assertRaises(ValueError):
                locate_board(image, config)

    def test_overlay_masks_outside_without_changing_ocr_input(self):
        image = np.full((400, 600, 3), 200, dtype=np.uint8)
        before = image.copy()
        board, overlay, _ = locate_board(image, PipelineConfig(roi=[0, 30, 600, 320]))
        np.testing.assert_array_equal(image, before)
        np.testing.assert_array_equal(board, before[30:350])
        np.testing.assert_array_equal(overlay[150, 150], before[150, 150])
        self.assertLess(int(overlay[0, 300, 0]), int(image[0, 300, 0]))
        self.assertGreater(int(overlay[150, 0, 2]), 200)  # 贴左边缘的边线仍清晰可见

    def test_rejects_invalid_config_and_existing_output(self):
        for config in (PipelineConfig(sample_interval_s=0), PipelineConfig(start_s=float("nan")),
                       PipelineConfig(max_frames=True), PipelineConfig(end_s=-1),
                       PipelineConfig(roi=[0, 0, 20, 20], corners=[[0, 0]] * 4)):
            with self.assertRaises(ValueError):
                config.validate()
        from cv_engine.cli import main
        target = self.root / "existing"
        target.mkdir()
        (target / "keep.txt").write_text("保留")
        with patch("cv_engine.writer.RUNS", self.root):
            self.assertEqual(main(["--video", str(self.video), "--run-id", "existing"]), 1)
        self.assertEqual((target / "keep.txt").read_text(), "保留")


if __name__ == "__main__":
    unittest.main()
