"""门控语义测试：参考提交、遮挡恢复、人体运动屏蔽和时间单位。"""
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

from cv_engine.config import PipelineConfig
from cv_engine.contracts import OcrBox
from cv_engine.pipeline import run
from cv_engine.stages.s03_pose import project_people
from cv_engine.stages.s04_gate import ChangeGate
from cv_engine.writer import RunWriter


class ChangeGateTests(unittest.TestCase):
    def setUp(self):
        self.image = np.full((160, 240, 3), 220, dtype="uint8")
        self.mask = np.zeros((160, 240), dtype="uint8")
        self.config = PipelineConfig(gate_mode="occlusion_change")

    def decide(self, gate, image=None, mask=None, ts=5, occlusion=0):
        return gate.decide(self.image if image is None else image, self.mask if mask is None else mask,
                           ts=ts, occlusion=occlusion)

    def test_skip_does_not_consume_change_and_only_commit_updates_reference(self):
        gate = ChangeGate(self.config)
        self.assertEqual(self.decide(gate, occlusion=.8)["reason"], "occluded")
        self.assertIsNone(gate.reference)
        self.assertEqual(self.decide(gate)["reason"], "first_visible")
        self.assertIsNone(gate.reference)  # 尚未执行 OCR
        gate.commit(self.image, self.mask, 5)
        changed = self.image.copy()
        cv2.rectangle(changed, (40, 60), (160, 90), (0, 0, 0), -1)
        self.assertEqual(self.decide(gate, changed, ts=6)["reason"], "cooldown")
        self.assertEqual(self.decide(gate, changed, ts=10, occlusion=.8)["reason"], "occluded")
        decision = self.decide(gate, changed, ts=11)
        self.assertEqual(decision["reason"], "changed")
        self.assertEqual(decision["reference_ts"], 5)

    def test_identical_skips_then_periodically_refreshes_without_overriding_occlusion(self):
        gate = ChangeGate(self.config)
        gate.commit(self.image, self.mask, 0)
        self.assertEqual(self.decide(gate)["reason"], "unchanged")
        self.assertEqual(self.decide(gate, ts=30)["reason"], "max_gap")
        self.assertEqual(self.decide(gate, ts=60, occlusion=.8)["reason"], "occluded")

    def test_changes_inside_person_mask_do_not_trigger_ocr(self):
        gate = ChangeGate(self.config)
        mask = self.mask.copy()
        mask[50:90, 30:160] = 255
        gate.commit(self.image, mask, 0)
        moved = self.image.copy()
        moved[50:90, 30:160] = 0
        decision = self.decide(gate, moved, mask=mask, occlusion=.15)
        self.assertEqual(decision["reason"], "unchanged")
        self.assertAlmostEqual(decision["ssim"], 1, places=4)

    def test_newly_visible_region_triggers_even_if_common_pixels_unchanged(self):
        gate = ChangeGate(self.config)
        hidden = self.mask.copy()
        hidden[50:90, 30:160] = 255
        gate.commit(self.image, hidden, 0)
        self.assertEqual(self.decide(gate)["reason"], "visibility_recovery")

    def test_erased_ink_is_a_change_even_without_new_dark_pixels(self):
        gate = ChangeGate(self.config)
        written = self.image.copy()
        cv2.putText(written, "TEST", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 5)
        gate.commit(written, self.mask, 0)
        self.assertEqual(self.decide(gate)["reason"], "changed")

    def test_people_union_is_board_coverage_and_does_not_double_count(self):
        calibration = {"output_size": [100, 100], "source_to_board": np.eye(3).tolist()}
        people = [{"bbox": [10, 10, 40, 40]}, {"bbox": [20, 10, 50, 40]}]
        _, ratio = project_people(people, calibration)
        self.assertAlmostEqual(ratio, 31 * 41 / 10000)
        _, ratio = project_people([{"bbox": [-50, -50, 150, 150]}], calibration)
        self.assertEqual(ratio, 1)  # 若误用 IoU 会得到远小于 1 的结果


class GatedPipelineTests(unittest.TestCase):
    def test_all_occluded_skips_ocr_initialization_and_writes_empty_results(self):
        self.check_pipeline(occluded=True)

    def test_stable_frames_reuse_reference_and_skip_duplicate_ocr(self):
        self.check_pipeline(occluded=False)

    def check_pipeline(self, occluded):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            video = root / "clip.avi"
            encoder = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10, (96, 72))
            self.assertTrue(encoder.isOpened())
            for _ in range(20):
                encoder.write(np.full((72, 96, 3), 220, dtype="uint8"))
            encoder.release()
            created = []

            class FakePose:
                def __init__(self, config):
                    pass

                def detect(self, image):
                    return ([{"bbox": [0, 0, 95, 71], "score": .9, "keypoints": [[0, 0, 0]] * 17}]
                            if occluded else [])

            class FakeOcr:
                def __init__(self, config):
                    created.append(self)

                def recognize(self, image, *, frame, ts, call):
                    return [OcrBox(text="板书原文", poly=[[1, 1], [20, 1], [20, 10], [1, 10]],
                                   score=.9, frame=frame, ts=ts, ocr_call=call)]

            config = PipelineConfig(gate_mode="occlusion_change", max_frames=3,
                                    sample_interval_s=.5, cooldown_s=0)
            writer = RunWriter("gated", root=root / "run")
            result = run(video, config, writer, engine_factory=FakeOcr, pose_factory=FakePose)
            self.assertEqual(result["errors"], [])
            expected = 0 if occluded else 1
            self.assertEqual(len(created), expected)
            self.assertEqual(writer.manifest.stage("06").metrics["calls"], expected)
            self.assertEqual(writer.manifest.stage("04").metrics["passed"], expected)
            self.assertTrue((writer.root / "04_gate/gate.json").is_file())
            self.assertEqual(writer.manifest.stage("03").status, "done")
            if occluded:
                self.assertIn("没有执行 OCR", (writer.root / "08_notes/notes.txt").read_text())


if __name__ == "__main__":
    unittest.main()
