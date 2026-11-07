"""阶段实现标注：代码文件 / 核心函数 / 核心参数。

数据只在 annotations/stages.yaml 维护，与 manifest（运行数据）解耦。
本模块只负责取数与归一化，HTML 由 components.impl_note 生成。
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import components as c

ANNOTATIONS = Path(__file__).resolve().parents[1] / "annotations" / "stages.yaml"


def load(path: Path | None = None) -> dict:
    p = Path(path) if path else ANNOTATIONS
    if not p.is_file():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return {}
    # YAML 1.1：未加引号的 01 会解析成整数 1，统一还原成两位编号
    return {str(k).zfill(2) if str(k).isdigit() else str(k): v
            for k, v in data.items() if isinstance(v, dict)}


def _funcs(raw) -> list[tuple[str, str]]:
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for f in raw or []:
        if isinstance(f, dict):
            out.append((str(f.get("name", "")), str(f.get("note", ""))))
        elif f:
            out.append((str(f), ""))
    return [pair for pair in out if pair[0]]


def stage(no: str, path: Path | None = None) -> dict:
    return load(path).get(str(no).zfill(2), {})


def render(no: str, *, open: bool = False, path: Path | None = None) -> str:
    """无标注时返回空串，页面不显示占位。"""
    d = stage(no, path)
    if not d:
        return ""
    files = d.get("files") or []
    if isinstance(files, str):
        files = [files]
    params = d.get("params") or {}
    pairs = [(str(k), str(v)) for k, v in params.items()] if isinstance(params, dict) else []
    return c.impl_note([str(f) for f in files if f], _funcs(d.get("funcs")), pairs,
                       open=open, draft=bool(d.get("draft", False)),
                       note=str(d.get("note", "")))
