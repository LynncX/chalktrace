"""复合模板：把 partitions/*.yaml 的声明翻译成 Tab。

kind 决定骨架，YAML 只提供数据：
    stage     指标行 + 图组 + 数据表 + 折叠说明
    overview  大数字 + 阶段进度条 + 产物索引
    items     条目证据卡网格
    compare   对照表

需要循环 / 条件 / 跨 tab 跳转时，可另写 partitions/*.py 暴露 TAB 或 render(ctx)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import annotations, components as c
from .assets import Asset

_TabRender = Callable[[object], str]
_ASSET_KEYS = {"path", "caption", "group", "alt", "mode", "poster"}


@dataclass
class Tab:
    no: str
    name: str
    short: str
    render: _TabRender


def _asset(ctx, spec: dict):
    kw = {k: v for k, v in spec.items() if k in _ASSET_KEYS}
    kw.setdefault("group", ctx_no_group(ctx, spec))
    return ctx.asset(**kw)


def ctx_no_group(ctx, spec: dict) -> str:
    """未显式指定时，同一 tab 的图自动成一组，供 lightbox 翻页。"""
    return f"tab-{spec.get('__tab_no__', 'misc')}"


def _figures(ctx, specs: list[dict], no: str) -> list:
    out = []
    for s in specs or []:
        if not s.get("path"):
            continue
        s = dict(s)
        s["__tab_no__"] = no
        out.append(_asset(ctx, s))
    return out


def _tables(ctx, specs: list[dict]):
    parts = []
    for s in specs or []:
        rows = ctx.read_json(s.get("path", ""))
        if isinstance(rows, dict):
            rows = rows.get("rows", list(rows.values()))
        parts.append(c.table(rows, s.get("columns"), title=s.get("title", "")))
    return parts


def _folds(specs: list[dict]):
    return [c.details(s.get("title", "详情"), s.get("body", "")) for s in specs or []]


def _render_stage(ctx, spec: dict) -> str:
    no = spec["no"]
    parts = [
        c.stage_header(no, spec.get("name", ""), ctx.status_of(no)),
        c.metric_row([ctx.resolve_metric(m) for m in spec.get("metrics", [])]),
        c.gallery(_figures(ctx, spec.get("figures", []), no), cols=spec.get("cols")),
        *_tables(ctx, spec.get("tables", [])),
        *_folds(spec.get("folds", [])),
    ]
    return c.card_stack(*parts)


def _render_overview(ctx, spec: dict) -> str:
    parts = [
        c.metric_row([ctx.resolve_metric(m) for m in spec.get("metrics", [])]),
        c.stage_strip(ctx.manifest.get("stages", {})),
        c.gallery(_figures(ctx, spec.get("figures", []), spec["no"]), cols=spec.get("cols")),
    ]
    files = ctx.manifest.get("files", [])
    if files:
        parts.append(c.card("产物索引", c.file_index(files)))
    parts.extend(_tables(ctx, spec.get("tables", [])))
    parts.extend(_folds(spec.get("folds", [])))
    return c.card_stack(*parts)


def _render_items(ctx, spec: dict) -> str:
    cards = []
    for it in ctx.manifest.get("items", []):
        frame = ctx.asset(it.get("frame", ""), caption="原帧", group="items")
        crop = ctx.asset(it.get("crop", ""), caption="裁剪", group="items")
        cards.append(c.evidence_card(
            item_id=it.get("item_id", ""),
            text=it.get("text", ""),
            span=(it.get("first_seen_sec", 0), it.get("last_seen_sec", 0)),
            frame=frame, crop=crop,
            ocr_link=it.get("ocr_link", ""),
            status=it.get("status", "done"),
        ))
    parts = [c.card("条目证据", c.card_grid(cards), badge=f"{len(cards)} 条")] if cards else []
    parts.extend(_folds(spec.get("folds", [])))
    return c.card_stack(*parts)


def _render_compare(ctx, spec: dict) -> str:
    rows = ctx.manifest.get("compare", [])
    if spec.get("path"):
        rows = ctx.read_json(spec["path"])
    parts = [
        c.metric_row([ctx.resolve_metric(m) for m in spec.get("metrics", [])]),
        c.table(rows, spec.get("columns"), title=spec.get("title", "")),
        c.gallery(_figures(ctx, spec.get("figures", []), spec["no"]), cols=spec.get("cols")),
        *_folds(spec.get("folds", [])),
    ]
    return c.card_stack(*parts)


_RENDERERS = {
    "stage": _render_stage,
    "overview": _render_overview,
    "items": _render_items,
    "compare": _render_compare,
}


def make_tab(spec: dict) -> Tab:
    raw_no = spec.get("no", spec.get(False, ""))   # 兼容 YAML 1.1 的裸键 no → False
    if raw_no in (None, ""):
        raise ValueError(f"tab 缺少 no：{spec.get('name', spec)}")
    no = str(raw_no).zfill(2)
    name = str(spec.get("name", no))
    short = str(spec.get("short", name))
    kind = str(spec.get("kind", "stage"))
    if kind not in _RENDERERS:
        raise ValueError(f"tab {no} 的 kind={kind!r} 未知，可选：{', '.join(_RENDERERS)}")
    spec = dict(spec, no=no)
    show = spec.get("annotations", True)   # False 关闭 / "open" 默认展开

    def render(ctx) -> str:
        body = _RENDERERS[kind](ctx, spec)
        if show:
            body += annotations.render(no, open=(show == "open"))
        return body

    return Tab(no=no, name=name, short=short, render=render)
