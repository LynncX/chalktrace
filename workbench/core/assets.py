"""素材解析层：把 Asset 说明解析成**不含 HTML** 的 ResolvedAsset。

三种构建模式（由 build.py 的 --assets 控制）：

    link    不塞媒体：全部走相对路径，HTML 最小，适合本地调试
    inline  全塞：所有媒体 base64 内嵌，单文件最完整，体积最大
    tiered  分级（默认）：按体积分三档，兼顾体积与断网可看

tab 作者只写 Asset(path)，永远不碰 base64 / 路径拼接 / 转义。
HTML 标签只在 components.py 里生成。
"""
from __future__ import annotations

import base64
import io
import mimetypes
import os
from dataclasses import dataclass, field
from pathlib import Path

try:                                    # Pillow 只用于分级模式的缩略图，缺失时自动降级
    from PIL import Image
except ImportError:                     # pragma: no cover
    Image = None

# --- 分级阈值（唯一定义处，改这里就能调档） ---
TIER_INLINE_MAX = 100 * 1024            # < 100 KB：直接内联
TIER_THUMB_MAX = 2 * 1024 * 1024        # 100 KB – 2 MB：缩略图内嵌 + 原图引用
THUMB_MAX_PX = 900
THUMB_QUALITY = 72

MODES = ("link", "inline", "tiered")
MODE_ALIASES = {
    "local": "link", "none": "link", "path": "link",
    "all": "inline", "full": "inline", "embed": "inline",
    "auto": "tiered", "graded": "tiered",
}

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg"}
VIDEO_EXT = {".mp4", ".webm", ".mov", ".avi", ".mkv"}
TEXT_EXT = {".json", ".txt", ".md", ".csv", ".log", ".yaml", ".yml"}


def normalize_mode(value: str) -> str:
    """接受别名；非法值直接报错，不静默回退。"""
    v = (value or "").strip().lower()
    v = MODE_ALIASES.get(v, v)
    if v not in MODES:
        raise ValueError(f"未知素材模式 {value!r}，可选：{', '.join(MODES)}（或别名 {', '.join(MODE_ALIASES)}）")
    return v


@dataclass
class Asset:
    path: str                            # 相对 runs/<run_id>/
    caption: str = ""
    group: str = ""                      # lightbox 分组
    alt: str = ""
    mode: str | None = None              # 单素材覆盖：inline | link | thumb
    poster: str = ""                     # 视频海报图路径


@dataclass
class ResolvedAsset:
    kind: str                            # image | video | pdf | text | binary | missing
    src: str = ""                        # 相对路径或 data URI
    fallback: str = ""                   # onerror 回退用的内嵌 data URI
    poster: str = ""                     # 视频海报（data URI 或相对路径）
    inline_text: str = ""                # 文本类素材的内联正文
    caption: str = ""
    alt: str = ""
    group: str = ""
    tier: str = ""                       # inline | thumb | link | text
    size: int = 0
    note: str = ""
    missing: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def embedded(self) -> bool:
        return bool(self.src.startswith("data:") or self.inline_text)


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext == ".pdf":
        return "pdf"
    if ext in TEXT_EXT:
        return "text"
    return "binary"


def _mime(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def data_uri(path: Path) -> str:
    return f"data:{_mime(path)};base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def thumb_data_uri(path: Path) -> str:
    """把图片压成内嵌 JPEG 缩略图；Pillow 不可用或解码失败时返回空串。"""
    if Image is None:
        return ""
    try:
        with Image.open(path) as im:
            im = im.convert("RGB")
            im.thumbnail((THUMB_MAX_PX, THUMB_MAX_PX))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=THUMB_QUALITY, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:                    # 损坏 / 非真实图片 / SVG
        return ""


def _rel(path: Path, out_dir: Path) -> str:
    return os.path.relpath(path, out_dir).replace(os.sep, "/")


def resolve(ctx, asset: Asset, *, mode: str, out_dir: Path) -> ResolvedAsset:
    """核心分发。ctx 只需提供 path(rel) -> Path。"""
    path = ctx.path(asset.path)
    out_dir = Path(out_dir).resolve()
    r = ResolvedAsset(
        kind=kind_of(path), caption=asset.caption, alt=asset.alt or asset.caption,
        group=asset.group,
    )

    if not path.is_file():
        r.kind, r.missing = "missing", True
        r.note = f"产物缺失：{asset.path}"
        return r

    r.size = path.stat().st_size
    effective = normalize_mode(asset.mode or mode) if asset.mode != "thumb" else "thumb"

    # 海报（link / 分级下给视频兜底，永远内嵌，保证断网也有画面）
    if asset.poster:
        poster_path = ctx.path(asset.poster)
        if poster_path.is_file():
            r.poster = thumb_data_uri(poster_path) or data_uri(poster_path)

    # 文本类：内联正文（比 base64 更可读、可搜索）
    if r.kind == "text":
        if effective == "link":
            r.tier, r.src = "link", _rel(path, out_dir)
        else:
            try:
                r.inline_text = path.read_text(encoding="utf-8", errors="replace")
                r.tier = "text"
            except OSError:
                r.tier, r.src = "link", _rel(path, out_dir)
        return r

    if effective == "link":
        r.tier, r.src = "link", _rel(path, out_dir)
        return r

    if effective == "inline":
        r.tier, r.src = "inline", data_uri(path)
        return r

    if effective == "thumb":             # 手动强制「缩略图内嵌 + 原图引用」
        r.tier, r.src = "thumb", _rel(path, out_dir)
        r.fallback = thumb_data_uri(path)
        if not r.fallback:
            r.src, r.tier = data_uri(path), "inline"
            r.warnings.append("Pillow 不可用，缩略图降级为原图内嵌")
        return r

    # ---- tiered：按体积分三档 ----
    if r.size < TIER_INLINE_MAX:
        r.tier, r.src = "inline", data_uri(path)
    elif r.size <= TIER_THUMB_MAX and r.kind == "image":
        r.tier, r.src = "thumb", _rel(path, out_dir)
        r.fallback = thumb_data_uri(path)
        if not r.fallback:
            r.src, r.tier = data_uri(path), "inline"
            r.warnings.append("Pillow 不可用，缩略图降级为原图内嵌")
    else:
        r.tier, r.src = "link", _rel(path, out_dir)
        if r.kind == "image":            # 第③档：内嵌海报兜底，原图只引用
            r.fallback = thumb_data_uri(path)
        if r.kind == "video" and not r.poster:
            r.note = "原始视频未内嵌，请同目录保留媒体文件"
    return r
