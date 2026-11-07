"""复合模板：把 partitions/*.yaml 的声明翻译成 Tab。

kind 决定骨架，YAML 只提供数据：
    stage     指标行 + 图组 + 数据表 + 折叠说明
    overview  大数字 + 阶段进度条 + 产物索引
    items     条目证据卡网格
    compare   对照表
    variants  实验页：列=变体 / 行=样本，等尺寸对齐 + 逐图对照滑杆

需要循环 / 条件 / 跨 tab 跳转时，可另写 partitions/*.py 暴露 TAB 或 render(ctx)。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import annotations, components as c
from .assets import IMAGE_EXT, VIDEO_EXT, Asset

_TabRender = Callable[[object], str]
_ASSET_KEYS = {"path", "caption", "group", "alt", "mode", "poster"}
_MEDIA_EXT = IMAGE_EXT | VIDEO_EXT | {".pdf"}
_GLOB_DEFAULT_LIMIT = 24
_VARIANT_DEFAULT_LIMIT = 12


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


def _natkey(s: str):
    """自然序：frame_2 排在 frame_10 前面。"""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", s)]


def _expand_glob(ctx, spec: dict) -> list:
    """展开目录里的真实媒体文件；扫不到就静默跳过，不生成缺失占位、不反推。"""
    root = ctx.root.resolve()
    try:
        candidates = list(ctx.root.glob(str(spec.get("glob", ""))))
    except (ValueError, OSError, NotImplementedError):
        return []
    found = []
    for p in candidates:
        if not p.is_file() or p.suffix.lower() not in _MEDIA_EXT:
            continue
        try:                               # 必须 resolve：字符串 relative_to 拦不住 ".."
            rel = p.resolve().relative_to(root).as_posix()
        except ValueError:                 # 越出 run 目录，忽略
            continue
        found.append((rel, p))
    found.sort(key=lambda pair: _natkey(Path(pair[0]).name))
    caption = str(spec.get("caption", ""))
    out = []
    for rel, p in found[:int(spec.get("limit", _GLOB_DEFAULT_LIMIT))]:
        item = {k: v for k, v in spec.items()
                if k not in ("glob", "caption", "limit")}
        item["path"] = rel
        item["caption"] = caption.replace("{stem}", p.stem) if caption else p.stem
        item["__tab_no__"] = spec.get("__tab_no__", "misc")
        out.append(_asset(ctx, item))
    return out


def _figures(ctx, specs: list[dict], no: str) -> list:
    out = []
    for s in specs or []:
        if not (s.get("path") or s.get("glob")):
            continue
        s = dict(s, __tab_no__=no)
        out.extend(_expand_glob(ctx, s) if s.get("glob") else [_asset(ctx, s)])
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
    parts.append(c.gallery(_figures(ctx, spec.get("figures", []), spec["no"]),
                           cols=spec.get("cols")))
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


def _render_variants(ctx, spec: dict) -> str:
    """实验页：同一批样本 × 多个参数变体，逐格放真实结果图并强制等尺寸对齐。"""
    variants = list(ctx.manifest.get("variants") or [])
    samples = list(ctx.manifest.get("samples") or [])[:int(spec.get("limit", _VARIANT_DEFAULT_LIMIT))]
    winner = str(ctx.manifest.get("winner", "") or spec.get("winner", "") or "")
    by_id = {str(v.get("id", v.get("name", ""))): v for v in variants}
    no = spec["no"]
    cache: dict[tuple[str, str], tuple] = {}

    def figure(v: dict, sid: str):
        vid = str(v.get("id", v.get("name", "")))
        key = (vid, sid)
        if key not in cache:
            rel = (v.get("images") or {}).get(sid, "")
            cap = str((v.get("captions") or {}).get(sid, ""))
            a = ctx.asset(rel, caption=cap, alt=f"{sid} · {v.get('name', vid)}",
                          group=f"exp-{no}-{sid}")   # 同一行图可横向翻页
            cache[key] = (a, c.asset_figure(a))
        return cache[key]

    cells = {}
    for s in samples:
        sid = str(s.get("id", ""))
        for v in variants:
            vid = str(v.get("id", v.get("name", "")))
            cells[(sid, vid)] = figure(v, sid)[1]

    parts = [
        c.metric_row([ctx.resolve_metric(m) for m in spec.get("metrics", [])]),
        c.variant_grid(samples, variants, cells, winner=winner),
    ]

    # 首变体与选中变体的逐图对照滑杆；缺任一图就跳过该样本，不补图
    if spec.get("slider") and winner in by_id and len(variants) > 1:
        base = variants[0]
        cases = []
        for s in samples:
            sid = str(s.get("id", ""))
            a, _ = figure(base, sid)
            b, _ = figure(by_id[winner], sid)
            case = c.slider_pair(a, b, label=f"样本 {sid}",
                                 label_a=str(base.get("name", "")),
                                 label_b=str(by_id[winner].get("name", "")))
            if case:
                cases.append(case)
        if cases:
            parts.append(c.card("逐图对照", "".join(cases)))

    parts.extend(_tables(ctx, spec.get("tables", [])))
    parts.extend(_folds(spec.get("folds", [])))
    return c.card_stack(*parts)


_RENDERERS = {
    "stage": _render_stage,
    "overview": _render_overview,
    "items": _render_items,
    "compare": _render_compare,
    "variants": _render_variants,
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
