"""工作台骨架自检：产物契约、三档素材、YAML 发现、缺失降级。

运行：python -m unittest discover -s workbench/tests -v
"""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

import yaml

from workbench import build as wb_build
from workbench.core import annotations, assets, components as c, registry
from workbench.core.context import RunContext
from workbench.core.templates import make_tab

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "runs" / "demo_mock"
PARTITIONS = ROOT / "workbench" / "partitions"


class AssetModeTests(unittest.TestCase):
    def test_normalize_mode(self):
        self.assertEqual(assets.normalize_mode("local"), "link")
        self.assertEqual(assets.normalize_mode("all"), "inline")
        self.assertEqual(assets.normalize_mode("auto"), "tiered")
        self.assertEqual(assets.normalize_mode("tiered"), "tiered")
        with self.assertRaises(ValueError):
            assets.normalize_mode("whatever")

    def test_yaml_bare_no_key(self):
        spec = yaml.safe_load('no: "04"\nname: 门控\nshort: 门控\nkind: stage\n')
        self.assertEqual(make_tab(spec).no, "04")   # YAML 1.1 把 no 解析成 False

    def test_registry_discovers_all_tabs(self):
        tabs = registry.discover(PARTITIONS)
        self.assertEqual(len(tabs), 11)
        self.assertEqual(len({t.no for t in tabs}), 11)
        self.assertEqual(tabs[0].no, "00")

    def test_tier_by_size(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "small.png").write_bytes(
                __import__("base64").b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="))
            (root / "big.bin").write_bytes(b"x" * (3 * 1024 * 1024))
            ctx = RunContext(root)
            self.assertEqual(ctx.asset("small.png", mode="auto").tier, "inline")
            big = ctx.asset("big.bin")
            self.assertEqual(big.tier, "link")
            self.assertFalse(big.embedded)
            link = RunContext(root, assets_mode="link").asset("small.png")
            self.assertEqual(link.tier, "link")
            full = RunContext(root, assets_mode="inline").asset("big.bin")
            self.assertEqual(full.tier, "inline")
            self.assertTrue(full.src.startswith("data:"))

    def test_missing_asset_is_placeholder(self):
        ctx = RunContext(DEMO)
        r = ctx.asset("media/03_pose/pose_demo.mp4", caption="姿态演示视频")
        self.assertTrue(r.missing)
        self.assertIn("缺失", c.asset_figure(r))

    def test_escape(self):
        self.assertEqual(c.esc('<a href="x">&'), "&lt;a href=&quot;x&quot;&gt;&amp;")


class BuildTests(unittest.TestCase):
    def test_three_modes_differ_and_are_self_consistent(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            results = {}
            for mode in assets.MODES:
                info = wb_build.build("demo_mock", assets_mode=mode,
                                      out=str(out / f"{mode}.html"))
                results[mode] = info
                html = info["path"].read_text(encoding="utf-8")
                self.assertNotIn("{{WB_", html)
                self.assertIn('class="wb-lightbox"', html)
            self.assertEqual(results["link"]["embedded"], 0)
            self.assertGreater(results["tiered"]["embedded"], 0)
            self.assertLess(results["link"]["bytes"], results["tiered"]["bytes"])
            self.assertLess(results["tiered"]["bytes"], results["inline"]["bytes"])
            inline = (out / "inline.html").read_text(encoding="utf-8")
            self.assertNotIn('src="media/', inline)
            self.assertNotIn('src="../media/', inline)
            tiered = (out / "tiered.html").read_text(encoding="utf-8")
            self.assertIn("data-fallback=", tiered)
            self.assertIn("缺失", tiered)

    def test_reproducible(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            a = wb_build.build("demo_mock", out=str(out / "a.html"))["path"].read_text(encoding="utf-8")
            b = wb_build.build("demo_mock", out=str(out / "b.html"))["path"].read_text(encoding="utf-8")
            self.assertEqual(a, b)

    def test_annotations_appear_in_html(self):
        with tempfile.TemporaryDirectory() as td:
            html = wb_build.build("demo_mock", out=str(Path(td) / "x.html"))["path"].read_text(encoding="utf-8")
            self.assertEqual(html.count('class="wb-details wb-impl"'), 9)  # 01–09，00/10 无标注


class AnnotationTests(unittest.TestCase):
    def test_load_normalizes_stage_numbers(self):
        data = annotations.load()
        self.assertEqual(len(data), 9)
        self.assertIn("01", data)
        self.assertIn("09", data)
        self.assertNotIn("00", data)

    def test_impl_note_three_sections_and_escaping(self):
        html = annotations.render("04")
        self.assertIn('class="wb-details wb-impl"', html)
        self.assertNotIn("<details class=\"wb-details wb-impl\" open", html)  # 默认折叠
        self.assertIn("s04_gate.py", html)
        self.assertIn("partition_gate()", html)
        self.assertIn("SSIM_MAX", html)
        self.assertIn("待校准", html)
        self.assertIn('wb-impl-label">备注', html)
        escaped = c.impl_note(["a<b.py"], [("f()", "x&y")], [("K", "<0.88")])
        self.assertIn("&lt;", escaped)
        self.assertNotIn("a<b.py", escaped)

    def test_missing_or_disabled_or_open(self):
        self.assertEqual(annotations.render("00"), "")
        ctx = RunContext(DEMO)
        off = make_tab({"no": "01", "name": "x", "kind": "stage", "annotations": False})
        self.assertNotIn("wb-impl", off.render(ctx))
        on = make_tab({"no": "01", "name": "x", "kind": "stage", "annotations": "open"})
        self.assertIn('class="wb-details wb-impl" open', on.render(ctx))

    def test_py_partition_also_gets_annotation(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "04_custom.py"
            p.write_text("no = '04'\nname = '自定义'\nshort = '自定义'\n"
                         "def render(ctx):\n    return '<p>ok</p>'\n", encoding="utf-8")
            tab = registry.discover(Path(td))[0]
            self.assertIn("wb-impl", tab.render(RunContext(DEMO)))


class GlobFigureTests(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name)
        (self.root / "manifest.json").write_text("{}", encoding="utf-8")
        media = self.root / "media" / "s"
        media.mkdir(parents=True)
        tiny = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")
        for name in ("f_2.png", "f_10.png", "f_1.png", "notes.txt"):
            (media / name).write_bytes(tiny if name.endswith(".png") else b"text")
        self.ctx = RunContext(self.root, assets_mode="link")

    def tearDown(self):
        self.td.cleanup()

    @staticmethod
    def _tab(figures):
        return make_tab({"no": "01", "name": "x", "short": "x",
                         "kind": "stage", "figures": figures})

    def test_glob_discovers_in_natural_order_and_skips_non_media(self):
        html = self._tab([{"glob": "media/s/*.png", "caption": "{stem}"}]).render(self.ctx)
        self.assertEqual(html.count('class="wb-figure"'), 3)
        self.assertLess(html.index("f_1.png"), html.index("f_2.png"))
        self.assertLess(html.index("f_2.png"), html.index("f_10.png"))
        self.assertNotIn("notes.txt", html)

    def test_glob_limit_and_missing_is_silent(self):
        html = self._tab([{"glob": "media/s/*.png", "limit": 2},
                          {"glob": "media/none/*.png"}]).render(self.ctx)
        self.assertEqual(html.count('class="wb-figure"'), 2)
        self.assertNotIn("缺失", html)

    def test_explicit_path_missing_still_shows_placeholder(self):
        self.assertIn("缺失", self._tab([{"path": "media/s/nope.png"}]).render(self.ctx))

    def test_glob_cannot_escape_run_dir(self):
        self.assertEqual(self._tab([{"glob": "../*.png"}]).render(self.ctx).count('class="wb-figure"'), 0)


class ExperimentTests(unittest.TestCase):
    """实验页：kind 分发、等尺寸对齐、默认 link、run 契约不受影响。"""
    TINY = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.root = Path(self.td.name) / "exp_case"
        self.root.mkdir()
        mf = {
            "kind": "experiment", "run_id": "exp_case",
            "title": "06 OCR · <参数>实验", "stage_name": "OCR 识别",
            "winner": "v2",
            "samples": [{"id": "07", "title": "板书密集"}, {"id": "12"}],
            "variants": [
                {"id": "v1", "name": "baseline", "params": {"clahe": "off"},
                 "images": {"07": "media/v1/07.png", "12": "media/v1/12.png"},
                 "captions": {"07": "0.91"}},
                {"id": "v2", "name": "+ CLAHE", "params": {"clahe": "on"},
                 "images": {"07": "media/v2/07.png", "12": "media/v2/missing.png"},
                 "captions": {"07": "0.96"}},
            ],
            "compare": [{"配置": "baseline", "识别框": 12},
                        {"配置": "+ CLAHE", "识别框": 14}],
        }
        (self.root / "manifest.json").write_text(
            json.dumps(mf, ensure_ascii=False), encoding="utf-8")
        for rel in ("media/v1/07.png", "media/v1/12.png", "media/v2/07.png"):
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(self.TINY)

    def tearDown(self):
        self.td.cleanup()

    def _html(self, **kw) -> str:
        info = wb_build.build(str(self.root), out=str(Path(self.td.name) / "x.html"), **kw)
        return info["path"].read_text(encoding="utf-8")

    def test_kind_dispatches_experiment_partitions(self):
        info = wb_build.build(str(self.root), out=str(Path(self.td.name) / "x.html"))
        html = info["path"].read_text(encoding="utf-8")
        self.assertEqual(info["kind"], "experiment")
        self.assertEqual(info["tabs"], 2)
        self.assertIn("wb-vgrid", html)
        self.assertIn("单阶段实验", html)
        self.assertNotIn("{{WB_", html)
        self.assertNotIn('class="wb-details wb-impl"', html)  # 实验页不带阶段实现标注
        self.assertIn("&lt;参数&gt;", html)          # 标题照常转义

    def test_experiment_default_assets_link_and_override(self):
        link = wb_build.build(str(self.root), out=str(Path(self.td.name) / "link.html"))
        self.assertEqual(link["mode"], "link")
        self.assertEqual(link["embedded"], 0)
        inline = wb_build.build(str(self.root), assets_mode="inline",
                                out=str(Path(self.td.name) / "inline.html"))
        self.assertGreater(inline["embedded"], 0)

    def test_variant_grid_aligned_winner_and_placeholder(self):
        html = self._html()
        self.assertEqual(html.count('class="wb-vcell'), 4)   # 2 样本 × 2 变体
        self.assertEqual(html.count('class="wb-vparam"')
                         + html.count('class="wb-vparam is-winner"'), 2)
        self.assertIn("is-winner", html)
        self.assertIn("缺失", html)
        self.assertIn('data-lb="exp-00-07"', html)            # 同一行可翻页

    def test_slider_only_when_both_images_exist(self):
        html = self._html()
        self.assertEqual(html.count('class="wb-slider"'), 1)  # 样本 12 缺一图 → 跳过
        self.assertIn("baseline ⇄ + CLAHE", html)

    def test_experiment_partitions_are_valid_yaml(self):
        tabs = registry.discover(ROOT / "workbench" / "partitions_experiment")
        self.assertEqual([t.no for t in tabs], ["00", "01"])

    def test_run_contract_unchanged(self):
        info = wb_build.build("demo_mock", out=str(Path(self.td.name) / "run.html"))
        html = info["path"].read_text(encoding="utf-8")
        self.assertEqual(info["kind"], "run")
        self.assertEqual(info["tabs"], 11)
        self.assertEqual(info["mode"], "tiered")
        self.assertEqual(html.count('class="wb-details wb-impl"'), 9)

    def test_fixture_schema(self):
        mf = json.loads((ROOT / "workbench" / "fixtures" / "demo_experiment" / "manifest.json")
                        .read_text(encoding="utf-8"))
        sids = {s["id"] for s in mf["samples"]}
        self.assertEqual(mf["kind"], "experiment")
        self.assertIn(mf["winner"], {v["id"] for v in mf["variants"]})
        for v in mf["variants"]:
            self.assertTrue(set(v["images"]).issubset(sids))


if __name__ == "__main__":
    unittest.main(verbosity=2)
