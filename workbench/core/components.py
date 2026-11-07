"""原子组件：**全项目唯一允许拼接 HTML 标签的 Python 文件**。

设计约定（对应设计文档 §5.1）：默认视图只有大数字、图片和极短标题；
口径 / 阈值 / 复现说明一律进 <details>；来源与产物档位用极细色点表达，不写文字胶囊。
"""
from __future__ import annotations

from html import escape

from .assets import ResolvedAsset
from .context import Metric


def esc(value) -> str:
    return escape("" if value is None else str(value), quote=True)


# --- 极细标记 ---
_TIER_HINT = {
    "inline": "已内嵌",
    "thumb": "缩略图内嵌 · 原图引用",
    "link": "引用外部文件",
    "text": "正文内嵌",
}


def source_dot(tier: str) -> str:
    label = _TIER_HINT.get(tier, "")
    return f'<span class="wb-dot wb-dot-{esc(tier or "link")}" title="{esc(label)}"></span>'


def status_dot(status: str) -> str:
    s = status if status in ("done", "running", "pending") else "pending"
    return f'<span class="wb-status wb-status-{s}" title="{esc(s)}"></span>'


# --- 容器 ---
def card(title: str, body: str, *, badge: str = "") -> str:
    head = ""
    if title or badge:
        head = (f'<div class="wb-card-head"><h3>{esc(title)}</h3>'
                + (f'<span class="wb-badge">{esc(badge)}</span>' if badge else "")
                + "</div>")
    return f'<section class="wb-card">{head}{body}</section>'


def card_stack(*parts: str) -> str:
    return '<div class="wb-stack">' + "".join(p for p in parts if p) + "</div>"


def card_grid(cells: list[str], *, cols: int | None = None) -> str:
    style = f' style="--wb-cols:{int(cols)}"' if cols else ""
    return f'<div class="wb-grid"{style}>' + "".join(cells) + "</div>"


# --- 指标 ---
def metric_row(metrics: list[Metric]) -> str:
    if not metrics:
        return ""
    cells = []
    for m in metrics:
        unit = f'<span class="wb-unit">{esc(m.unit)}</span>' if m.unit else ""
        hint = f' title="{esc(m.hint)}"' if m.hint else ""
        cells.append(
            f'<div class="wb-metric"{hint}><span class="wb-metric-label">{esc(m.label)}</span>'
            f'<span class="wb-metric-value">{esc(m.value)}{unit}</span></div>'
        )
    return '<div class="wb-metrics">' + "".join(cells) + "</div>"


def stage_header(no: str, name: str, status: str = "pending") -> str:
    return (f'<div class="wb-stage-head">{status_dot(status)}'
            f'<span class="wb-stage-no">{esc(no)}</span>'
            f'<h2>{esc(name)}</h2></div>')


# --- 素材 ---
def missing_card(alt: str, note: str = "") -> str:
    return (f'<figure class="wb-figure wb-missing"><div class="wb-missing-box">'
            f'<span class="wb-missing-mark"></span><span>缺失</span></div>'
            f'<figcaption>{esc(alt)}'
            + (f'<span class="wb-note">{esc(note)}</span>' if note else "")
            + "</figcaption></figure>")


def _caption(a: ResolvedAsset) -> str:
    bits = [esc(a.caption or a.alt)] if (a.caption or a.alt) else []
    if a.note:
        bits.append(f'<span class="wb-note">{esc(a.note)}</span>')
    bits.append(source_dot(a.tier))
    return "<figcaption>" + "".join(bits) + "</figcaption>" if bits else ""


def asset_figure(a: ResolvedAsset) -> str:
    if a.missing:
        return missing_card(a.alt, a.note)

    if a.kind == "text":
        if a.inline_text:
            body = f'<pre class="wb-pre">{esc(a.inline_text)}</pre>'
        else:
            body = (f'<div class="wb-file-box"><a href="{esc(a.src)}">打开文本 ↗</a></div>')
        return f'<figure class="wb-figure wb-text-figure">{body}{_caption(a)}</figure>'

    if a.kind == "image":
        fb = (f' data-fallback="{esc(a.fallback)}" onerror="wbFallback(this)"'
              if a.fallback else "")
        lb = f' data-lb="{esc(a.group)}"' if a.group else ""
        return (f'<figure class="wb-figure"><img class="wb-media" loading="lazy"'
                f' src="{esc(a.src)}" alt="{esc(a.alt)}"{lb}{fb}>{_caption(a)}</figure>')

    if a.kind == "video":
        poster = f' poster="{esc(a.poster)}"' if a.poster else ""
        return (f'<figure class="wb-figure"><video class="wb-media" controls preload="none"'
                f' src="{esc(a.src)}"{poster}></video>{_caption(a)}</figure>')

    # pdf / 其它二进制：只给一个安静的入口，不占版面
    return (f'<figure class="wb-figure wb-link-figure"><a class="wb-file-link"'
            f' href="{esc(a.src)}" target="_blank" rel="noopener">'
            f'<span>{esc(a.caption or a.alt or a.src)}</span><span class="wb-arrow">↗</span>'
            f'</a>{_caption(a)}</figure>')


def gallery(assets: list[ResolvedAsset], *, cols: int | None = None) -> str:
    if not assets:
        return ""
    return ('<div class="wb-gallery"' + (f' style="--wb-cols:{int(cols)}"' if cols else "")
            + ">" + "".join(asset_figure(a) for a in assets) + "</div>")


# --- 表格 / 折叠 ---
def table(rows: list[dict], columns: list[str] | None = None, *, title: str = "") -> str:
    if not rows:
        return ""
    cols = columns or list(rows[0].keys())
    head = "".join(f"<th>{esc(c)}</th>" for c in cols)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols) + "</tr>"
        for r in rows
    )
    label = f'<div class="wb-table-label">{esc(title)}</div>' if title else ""
    return (f'{label}<div class="wb-table-wrap"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def details(title: str, body: str, *, open: bool = False) -> str:
    o = " open" if open else ""
    return (f'<details class="wb-details"{o}><summary>{esc(title)}</summary>'
            f'<div class="wb-details-body">{esc(body)}</div></details>')


def impl_note(files: list[str], funcs: list[tuple[str, str]],
              params: list[tuple[str, str]], *, open: bool = False,
              draft: bool = False, note: str = "") -> str:
    """阶段实现标注：代码 / 函数 / 参数三行，默认折叠，不占首屏版面。"""
    rows = []
    if files:
        rows.append(_impl_row("代码", "".join(
            f'<code class="wb-impl-code">{esc(f)}</code>' for f in files)))
    if funcs:
        rows.append(_impl_row("函数", "".join(
            f'<div class="wb-impl-line"><code>{esc(n)}</code>'
            + (f'<span class="wb-note">{esc(note)}</span>' if note else "")
            + "</div>" for n, note in funcs)))
    if params:
        rows.append(_impl_row("参数", "".join(
            f'<div class="wb-impl-line"><code>{esc(k)}</code>'
            f'<span class="wb-impl-eq">=</span><span>{esc(v)}</span></div>'
            for k, v in params)))
    if note:
        rows.append(_impl_row("备注", f'<span class="wb-impl-note">{esc(note)}</span>'))
    if not rows:
        return ""
    label = "实现标注" + (" · 待校准" if draft else "")
    o = " open" if open else ""
    return (f'<details class="wb-details wb-impl"{o}><summary>{esc(label)}</summary>'
            f'<div class="wb-details-body wb-impl-body">' + "".join(rows) + "</div></details>")


def _impl_row(label: str, body: str) -> str:
    return (f'<div class="wb-impl-row"><span class="wb-impl-label">{esc(label)}</span>'
            f'<div class="wb-impl-value">{body}</div></div>')


# --- 复合小件 ---
def evidence_card(*, item_id: str, text: str, span: tuple, frame: ResolvedAsset,
                  crop: ResolvedAsset, ocr_link: str = "", status: str = "") -> str:
    span_text = f"{span[0]:.1f} – {span[1]:.1f}s" if len(span) == 2 else ""
    link = (f'<a class="wb-inline-link" href="{esc(ocr_link)}">OCR 原文 ↗</a>'
            if ocr_link else "")
    return (f'<article class="wb-evidence"><div class="wb-evidence-top">'
            f'<span class="wb-id">{esc(item_id)}</span>{status_dot(status or "done")}'
            f'<span class="wb-span">{esc(span_text)}</span></div>'
            f'<p class="wb-evidence-text">{esc(text)}</p>'
            f'<div class="wb-evidence-media">{asset_figure(frame)}{asset_figure(crop)}</div>'
            f'<div class="wb-evidence-foot">{link}</div></article>')


def stage_strip(stages: dict) -> str:
    if not stages:
        return ""
    cells = []
    for no, st in sorted(stages.items()):
        cells.append(f'<div class="wb-strip-cell">{status_dot(st.get("status", "pending"))}'
                     f'<span class="wb-strip-no">{esc(no)}</span>'
                     f'<span class="wb-strip-name">{esc(st.get("name", ""))}</span></div>')
    return '<div class="wb-strip">' + "".join(cells) + "</div>"


def file_index(files: list[dict]) -> str:
    if not files:
        return ""
    rows = "".join(
        f'<a class="wb-index-row" href="{esc(f.get("path", ""))}" target="_blank" rel="noopener">'
        f'<span>{esc(f.get("path", ""))}</span><span>{esc(f.get("size", ""))}</span></a>'
        for f in files
    )
    return f'<div class="wb-index">{rows}</div>'


# --- 页面骨架零件 ---
def tab_button(tab_id: str, short: str, *, active: bool = False) -> str:
    a = " is-active" if active else ""
    return (f'<button class="wb-tab{a}" data-tab="{esc(tab_id)}" type="button">'
            f'{esc(short)}</button>')


def tab_panel(tab_id: str, body: str, *, active: bool = False) -> str:
    a = " is-active" if active else ""
    return (f'<section class="wb-panel{a}" data-panel="{esc(tab_id)}">'
            f'{body}</section>')
