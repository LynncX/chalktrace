"""契约层自检：字段形状、往返、校验、writer 落盘、writer → workbench 端到端。

    python -m unittest discover -s cv_engine/tests -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from cv_engine import contracts as k
from cv_engine.schema import (EXPERIMENT_SCHEMA, MANIFEST_SCHEMA, SCHEMA_FILES,
                              export, validate_manifest)
from cv_engine.writer import ExperimentWriter, RunWriter

FIX_RUN = ROOT / "workbench" / "fixtures" / "demo_mock" / "manifest.json"
FIX_EXP = ROOT / "workbench" / "fixtures" / "demo_experiment" / "manifest.json"
HAS_YAML = importlib.util.find_spec("yaml") is not None


def _flatten(obj, prefix=""):
    out = set()
    if isinstance(obj, dict):
        for key, val in obj.items():
            out |= _flatten(val, f"{prefix}.{key}")
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            out |= _flatten(val, f"{prefix}[{i}]")
    else:
        out.add(prefix)
    return out


class ContractTypes(unittest.TestCase):
    def test_new_run_shape(self):
        d = k.new_run("r1", video={"frames": 9000, "duration_s": 300.0}).to_dict()
        self.assertIsInstance(d["stages"], dict)
        self.assertEqual(tuple(d["stages"]), k.STAGE_IDS)
        self.assertTrue(all(s["status"] == "pending" for s in d["stages"].values()))
        self.assertEqual(d["video"]["duration_s"], 300.0)
        self.assertNotIn("duration_sec", d["video"])
        self.assertEqual(d["kind"], "run")

    def test_enum_value_in_stage_status(self):
        m = k.new_run("r1")
        m.set_stage("01", status=k.StageStatus.DONE, metrics={"sampled": 10})
        m.set_stage("02", status=k.StageStatus.RUNNING)
        d = m.to_dict()
        self.assertEqual(d["stages"]["01"]["status"], "done")
        self.assertEqual(d["stages"]["02"]["status"], "running")
        self.assertEqual(d["stages"]["01"]["metrics"]["sampled"], 10)

    def test_roundtrip_keeps_unknown_fields(self):
        d = k.new_run("r1", video={"frames": 1, "duration_s": 1.0}).to_dict()
        d["future_field"] = {"x": 1}
        d["items"] = [{"item_id": "I1", "text": "甲", "frame": "media/a.jpg",
                       "crop": "media/b.png", "new_key": 42}]
        back = k.load_manifest(d)
        out = back.to_dict()
        self.assertEqual(out["future_field"], {"x": 1})
        self.assertEqual(out["items"][0]["new_key"], 42)
        self.assertIsInstance(back.items[0], k.BoardItem)

    def test_legacy_fixtures_load_without_loss(self):
        for path, cls in ((FIX_RUN, k.RunManifest), (FIX_EXP, k.ExperimentManifest)):
            src = json.loads(path.read_text(encoding="utf-8"))
            obj = k.load_manifest(src)
            self.assertIsInstance(obj, cls)
            self.assertEqual(_flatten(src) - _flatten(obj.to_dict()), set())

    def test_safe_rel(self):
        self.assertEqual(k.safe_rel("media/05_enhance/a.png"), "media/05_enhance/a.png")
        for bad in ("../x.png", "/etc/passwd", "C:/x.png", "", "media/../../x"):
            with self.assertRaises(ValueError):
                k.safe_rel(bad)


class SchemaValidation(unittest.TestCase):
    def test_exported_json_in_sync(self):
        exported = {p.name: json.loads(p.read_text(encoding="utf-8"))
                    for p in export(tempfile.mkdtemp())}
        self.assertEqual(exported, SCHEMA_FILES)
        for name in ("manifest.schema.json", "experiment.schema.json"):
            self.assertEqual(json.loads((ROOT / "cv_engine" / name).read_text(encoding="utf-8")),
                             SCHEMA_FILES[name])

    def test_required_fields_and_refs(self):
        self.assertEqual(MANIFEST_SCHEMA["properties"]["stages"]["patternProperties"]["^0[1-9]$"]
                         ["properties"]["status"]["enum"], list(k.STAGE_STATUS_VALUES))
        self.assertIn("duration_s", MANIFEST_SCHEMA["properties"]["video"]["required"])

    def test_fixtures_pass(self):
        for path in (FIX_RUN, FIX_EXP):
            self.assertEqual(validate_manifest(json.loads(path.read_text(encoding="utf-8"))), [])

    def test_rejects_old_contract_and_unsafe_paths(self):
        bad = k.new_run("bad", video={"frames": 1, "duration_sec": 1.0}).to_dict()
        bad["stages"] = [{"stage_id": "01", "status": "skipped"}]
        bad["items"] = [{"item_id": "I1", "frame": "../outside.png", "crop": "",
                         "status": "archived"}]
        bad["files"] = [{"path": "/etc/passwd"}]
        errs = validate_manifest(bad)
        for needle in ("duration_sec", "必须是字典", "缺 frame/crop",
                       "不在三态内", "'..'", "'/etc/passwd'"):
            self.assertTrue(any(needle in e for e in errs), f"未拦下 {needle}：{errs}")

    def test_winner_must_exist(self):
        d = k.new_experiment("e", stage="06").to_dict()
        d["samples"] = [{"id": "07"}]
        d["variants"] = [{"id": "base", "images": {"07": "media/a.png"}}]
        d["winner"] = "nope"
        self.assertTrue(any("winner" in e for e in validate_manifest(d)))
        d["winner"] = "base"
        self.assertEqual(validate_manifest(d), [])


class RunWriterTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name) / "r1"

    def tearDown(self):
        self.td.cleanup()

    def _writer(self):
        return RunWriter("r1", root=self.root, video={"frames": 9000, "duration_s": 300.0})

    def test_incremental_status_is_on_disk(self):
        w = self._writer()
        d = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(d["stages"]["01"]["status"], "pending")
        w.begin_stage("01")
        d = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(d["stages"]["01"]["status"], "running")
        w.finish_stage("01", metrics={"sampled": 2236})
        d = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(d["stages"]["01"]["status"], "done")
        self.assertEqual(d["stages"]["01"]["metrics"]["sampled"], 2236)
        self.assertEqual(list(self.root.rglob("*.tmp")), [])

    def test_finalize_scans_files_and_validates(self):
        with self._writer() as w:
            w.write_json("01_frames/frames.json", [{"frame": 0}])
            w.write_bytes("media/01_frames/sample_0000.jpg", b"\xff\xd8")
            w.finish_stage("01", metrics={"sampled": 1})
            w.write_item(k.BoardItem(item_id="I1", text="甲", frame="media/07_items/f.jpg",
                                     crop="media/07_items/c.png"))
        d = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        paths = [f["path"] for f in d["files"]]
        self.assertIn("01_frames/frames.json", paths)
        self.assertIn("media/01_frames/sample_0000.jpg", paths)
        self.assertEqual(d["status"], "done")
        self.assertEqual(d["warnings"], [])
        self.assertEqual(validate_manifest(d), [])

    def test_rejects_path_traversal(self):
        with self._writer() as w:
            with self.assertRaises(ValueError):
                w.write_json("../escape.json", {})
            with self.assertRaises(ValueError):
                w.write_item({"item_id": "I1", "crop": "../../etc/passwd"})
            with self.assertRaises(ValueError):
                w.write_stage("01", status="failed")

    def test_context_manager_marks_failure(self):
        try:
            with self._writer():
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        d = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(d["status"], "failed")
        self.assertTrue(any("boom" in x for x in d["warnings"]))

    @unittest.skipUnless(HAS_YAML, "workbench 需要 PyYAML")
    def test_writer_output_renders_in_workbench(self):
        from workbench.build import build
        with self._writer() as w:
            w.write_json("01_frames/frames.json", [{"frame": 0, "ts": 0.0, "blur": 0.9, "kept": True}])
            w.write_bytes("media/01_frames/sample_0000.jpg", b"\xff\xd8")
            w.finish_stage("01", metrics={"sampled": 2236, "blur_dropped": 0})
            w.write_item(k.BoardItem(item_id="IT-001", text="货币政策",
                                     frame="media/07_items/f.jpg", crop="media/07_items/c.png"))
        info = build(str(self.root), assets_mode="link")
        self.assertEqual(info["kind"], "run")
        self.assertEqual(info["tabs"], 11)
        html = info["path"].read_text(encoding="utf-8")
        self.assertIn("2,236", html)
        self.assertIn("货币政策", html)
        self.assertEqual(html.count("{{WB_"), 0)


class ExperimentWriterTests(unittest.TestCase):
    def test_experiment_writer(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "e1"
            with ExperimentWriter("e1", stage="06", root=root) as w:
                w.add_sample("07", "板书密集")
                w.add_variant("base", images={"07": "media/base/s07.png"})
                w.add_variant("clahe", images={"07": "media/clahe/s07.png"})
                w.set_winner("clahe")
                w.set_compare([{"配置": "base", "识别框": 28}])
            d = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(d["kind"], "experiment")
            self.assertEqual(validate_manifest(d), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
