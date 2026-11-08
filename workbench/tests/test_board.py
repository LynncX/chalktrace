"""区域核验不猜测旧产物的路径或缺失的标定来源。"""
import json
from pathlib import Path
import tempfile
import unittest

from workbench.core.context import RunContext
from workbench.core.registry import discover


class BoardAuditTests(unittest.TestCase):
    def render(self, rows=None):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "manifest.json").write_text(json.dumps({"stages": {"02": {"status": "done"}}}))
            if rows is not None:
                (root / "02_board").mkdir()
                (root / "02_board/calibration.json").write_text(json.dumps(rows))
            tabs = discover(Path(__file__).resolve().parents[1] / "partitions")
            return next(tab for tab in tabs if tab.no == "02").render(RunContext(root))

    def test_missing_metadata_does_not_claim_manual_detection(self):
        page = self.render()
        self.assertIn("没有 calibration.json", page)
        self.assertIn("区域来源", page)
        self.assertNotIn("平均置信度", page)

    def test_old_metadata_does_not_invent_overlay_path(self):
        page = self.render([{"frame": 1, "ts": .1, "mode": "manual_roi",
                             "path": "media/02_board/board_1.png"}])
        self.assertIn("未记录产物路径", page)
        self.assertNotIn("calib_1.png", page)

    def test_full_frame_is_not_described_as_perspective_correction(self):
        page = self.render([{"frame": 1, "ts": .1, "mode": "full_frame",
                             "path": "board.png", "overlay_path": "calib.png"}])
        self.assertIn("全帧直通 · 未定位", page)
        self.assertIn("全帧直通结果", page)
        self.assertNotIn("透视校正结果", page)


if __name__ == "__main__":
    unittest.main()
