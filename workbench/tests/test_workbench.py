"""工作台骨架自检：产物契约、三档素材、YAML 发现、缺失降级。

运行：python -m unittest discover -s workbench/tests -v
"""
from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
