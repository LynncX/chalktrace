"""自动发现 partitions/ 下的 .yaml 与 .py，统一成 Tab 协议。

新增一个同构 tab = 丢一个 .yaml 进去，不改 build.py。
复杂 tab 写 .py，暴露 TAB 对象，或模块级 no / name / short / render(ctx)。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from . import annotations, templates

try:
    import yaml
except ImportError as exc:              # pragma: no cover
    raise RuntimeError(
        "workbench 需要 PyYAML：pip install -r workbench/requirements.txt"
    ) from exc


def _load_py(path: Path) -> templates.Tab:
    spec = importlib.util.spec_from_file_location(f"wb_partition_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    tab = getattr(mod, "TAB", None)
    if isinstance(tab, templates.Tab):
        out = tab
    else:
        if not callable(getattr(mod, "render", None)):
            raise ValueError(f"{path.name} 既没有 TAB，也没有 render(ctx)")
        out = templates.Tab(
            no=str(getattr(mod, "no", path.stem[:2])).zfill(2),
            name=str(getattr(mod, "name", path.stem)),
            short=str(getattr(mod, "short", getattr(mod, "name", path.stem))),
            render=mod.render,
        )
    # 与 YAML tab 一致地带上实现标注；模块级 annotations = False 可关闭
    if getattr(mod, "annotations", True):
        base = out.render

        def render(ctx, _base=base, _no=out.no):
            return _base(ctx) + annotations.render(_no)

        out.render = render
    return out


def discover(partitions_dir: Path, ctx=None) -> list[templates.Tab]:
    partitions_dir = Path(partitions_dir)
    tabs: list[templates.Tab] = []
    for p in sorted(partitions_dir.iterdir()):
        if p.name.startswith("_") or p.is_dir():
            continue
        if p.suffix in (".yaml", ".yml"):
            spec = yaml.safe_load(p.read_text(encoding="utf-8"))
            # YAML 1.1 会把裸键 `no` 解析成布尔 False，这里还原回来
            if isinstance(spec, dict) and False in spec:
                spec["no"] = spec.pop(False)
            if isinstance(spec, dict) and spec.get("enabled", True) is not False:
                tabs.append(templates.make_tab(spec))
        elif p.suffix == ".py":
            tabs.append(_load_py(p))

    seen = set()
    for t in tabs:
        if t.no in seen:
            raise ValueError(f"tab 编号重复：{t.no}")
        seen.add(t.no)
    return sorted(tabs, key=lambda t: t.no)
