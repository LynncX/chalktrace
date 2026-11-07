"""机读契约：JSON Schema（供非 Python 消费）+ 人工可读校验（供 writer / CI / 评测）。

    python -m cv_engine.schema            # 重新导出两个 .json
    from cv_engine.schema import validate_manifest
    errs = validate_manifest(json.load(open("runs/x/manifest.json")))

validate_manifest 返回中文错误列表，空列表即通过。它只校验「工作台能否正确渲染 +
路径是否安全」，不校验算法结果是否正确 —— 后者是 E 的评测职责。

注意：MANIFEST_SCHEMA 是本文件里的 Python dict，两个 .json 是它的导出物，
测试会断言三者一致；改 schema 后必须重跑 `python -m cv_engine.schema`。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import contracts as k

_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_SCHEMA_DIR = Path(__file__).resolve().parent

_STAGE_SCHEMA = {
    "type": "object",
    "required": ["status"],
    "properties": {
        "name": {"type": "string"},
        "status": {"enum": list(k.STAGE_STATUS_VALUES)},
        "metrics": {"type": "object"},
        "duration_s": {"type": "number"},
        "note": {"type": "string"},
    },
    "additionalProperties": True,   # 只加字段、不改含义
}

_ITEM_SCHEMA = {
    "type": "object",
    "required": ["item_id"],
    "properties": {
        "item_id": {"type": "string"},
        "text": {"type": "string"},
        "first_seen_sec": {"type": "number"},
        "last_seen_sec": {"type": "number"},
        "frame": {"type": "string"},
        "crop": {"type": "string"},
        "ocr_link": {"type": "string"},
        "status": {"enum": list(k.STAGE_STATUS_VALUES)},
        "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
        "evidence": {"type": "object"},
        "archived": {"type": "boolean"},
    },
    "additionalProperties": True,
}

MANIFEST_SCHEMA = {
    "$schema": _DRAFT,
    "$id": "manifest.schema.json",
    "title": "板书数字化 · 一次完整流水线（run）",
    "type": "object",
    "required": ["run_id", "video", "stages"],
    "properties": {
        "schema_version": {"type": "string"},
        "kind": {"enum": ["run"]},
        "run_id": {"type": "string", "minLength": 1},
        "title": {"type": "string"},
        "created_at": {"type": "string"},
        "status": {"enum": list(k.RUN_STATUS_VALUES)},
        "video": {
            "type": "object",
            "required": ["frames", "duration_s"],
            "properties": {
                "name": {"type": "string"},
                "frames": {"type": "integer", "minimum": 0},
                "fps": {"type": "number", "minimum": 0},
                "duration_s": {"type": "number", "minimum": 0},
                "width": {"type": "integer", "minimum": 0},
                "height": {"type": "integer", "minimum": 0},
            },
            "not": {"required": ["duration_sec"]},   # 旧架构文档里的错误键名，明确拒绝
            "additionalProperties": True,
        },
        "config": {"type": "object"},
        "stages": {
            "type": "object",
            "patternProperties": {"^0[1-9]$": _STAGE_SCHEMA},
            "additionalProperties": False,
        },
        "items": {"type": "array", "items": _ITEM_SCHEMA},
        "compare": {"type": "array", "items": {"type": "object"}},
        "files": {"type": "array", "items": {
            "type": "object", "required": ["path"],
            "properties": {"path": {"type": "string"}, "size": {}},
        }},
        "outputs": {"type": "object"},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": True,
}

_VARIANT_SCHEMA = {
    "type": "object",
    "required": ["id", "images"],
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "params": {"type": "object"},
        "images": {"type": "object", "additionalProperties": {"type": "string"}},
        "captions": {"type": "object", "additionalProperties": {"type": "string"}},
    },
    "additionalProperties": True,
}

EXPERIMENT_SCHEMA = {
    "$schema": _DRAFT,
    "$id": "experiment.schema.json",
    "title": "板书数字化 · 单阶段调参实验（experiment）",
    "type": "object",
    "required": ["kind", "run_id", "samples", "variants"],
    "properties": {
        "schema_version": {"type": "string"},
        "kind": {"enum": ["experiment"]},
        "run_id": {"type": "string", "minLength": 1},
        "title": {"type": "string"},
        "created_at": {"type": "string"},
        "stage": {"enum": list(k.STAGE_IDS)},
        "stage_name": {"type": "string"},
        "input": {"type": "string"},
        "winner": {"type": "string"},
        "samples": {"type": "array", "items": {
            "type": "object", "required": ["id"],
            "properties": {"id": {"type": "string"}, "title": {"type": "string"}},
        }},
        "variants": {"type": "array", "minItems": 1, "items": _VARIANT_SCHEMA},
        "compare": {"type": "array", "items": {"type": "object"}},
    },
    "additionalProperties": True,
}

SCHEMA_FILES = {
    "manifest.schema.json": MANIFEST_SCHEMA,
    "experiment.schema.json": EXPERIMENT_SCHEMA,
}


def _path(value, label: str, errors: list[str]) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, str):
        errors.append(f"{label} 必须是字符串路径：{value!r}")
        return
    try:
        k.safe_rel(value)
    except ValueError as exc:
        errors.append(f"{label} {exc}")


def _check_run(d: dict) -> list[str]:
    e: list[str] = []
    for key in ("run_id", "video", "stages"):
        if key not in d:
            e.append(f"缺少顶层字段 {key}")
    # schema_version 旧 manifest 可缺（kind 缺省即 run），但写错了必须拦住
    if "schema_version" in d and d["schema_version"] != k.SCHEMA_VERSION:
        e.append(f"schema_version={d['schema_version']!r}，当前契约是 {k.SCHEMA_VERSION!r}")
    v = d.get("video") or {}
    if not isinstance(v, dict):
        e.append("video 必须是对象")
    else:
        if "duration_sec" in v:
            e.append("video 用了旧键 duration_sec，必须改为 duration_s")
        for key in ("frames", "duration_s"):
            if key not in v:
                e.append(f"video 缺少 {key}")
            elif not isinstance(v[key], (int, float)):
                e.append(f"video.{key} 必须是数字")
    stages = d.get("stages") or {}
    if not isinstance(stages, dict):
        e.append("stages 必须是字典（键 '01'–'09'），不能是 list")
    else:
        for no, st in stages.items():
            if no not in k.STAGE_IDS:
                e.append(f"未知阶段编号 {no!r}（应为 01–09）")
            if not isinstance(st, dict):
                e.append(f"stages.{no} 必须是对象")
                continue
            status = st.get("status")
            if status not in k.STAGE_STATUS_VALUES:
                e.append(f"stages.{no}.status={status!r}，应为 {k.STAGE_STATUS_VALUES}")
            if "metrics" in st and not isinstance(st["metrics"], dict):
                e.append(f"stages.{no}.metrics 必须是对象")
    if "status" in d and d["status"] not in k.RUN_STATUS_VALUES:
        e.append(f"顶层 status={d['status']!r}，应为 {k.RUN_STATUS_VALUES}")
    for i, it in enumerate(d.get("items") or []):
        if not isinstance(it, dict):
            e.append(f"items[{i}] 必须是对象")
            continue
        if not it.get("item_id"):
            e.append(f"items[{i}] 缺少 item_id")
        if not it.get("frame") or not it.get("crop"):
            e.append(f"items[{i}] 缺 frame/crop，07 条目证据卡会开天窗")
        if it.get("status", "done") not in k.STAGE_STATUS_VALUES:
            e.append(f"items[{i}].status 不在三态内，页签会显示错误色点")
        for f in ("frame", "crop"):
            _path(it.get(f), f"items[{i}].{f}", e)
        for f, rel in (it.get("evidence") or {}).items():
            _path(rel, f"items[{i}].evidence.{f}", e)
    for i, f in enumerate(d.get("files") or []):
        if not isinstance(f, dict) or not f.get("path"):
            e.append(f"files[{i}] 缺少 path")
        else:
            _path(f["path"], f"files[{i}].path", e)
    for key, rel in (d.get("outputs") or {}).items():
        _path(rel, f"outputs.{key}", e)
    for key in ("compare", "warnings"):
        if key in d and not isinstance(d[key], list):
            e.append(f"{key} 必须是数组")
    return e


def _check_experiment(d: dict) -> list[str]:
    e: list[str] = []
    if d.get("kind") != "experiment":
        e.append("实验 manifest 必须带 kind: experiment")
    samples = d.get("samples") or []
    variants = d.get("variants") or []
    if not isinstance(samples, list) or not samples:
        e.append("samples 必须是非空数组")
    if not isinstance(variants, list) or not variants:
        e.append("variants 必须是非空数组")
    if d.get("stage") and d["stage"] not in k.STAGE_IDS:
        e.append(f"stage={d['stage']!r} 不是 01–09")
    ids = set()
    for i, v in enumerate(variants if isinstance(variants, list) else []):
        if not isinstance(v, dict) or not v.get("id"):
            e.append(f"variants[{i}] 缺少 id")
            continue
        ids.add(str(v["id"]))
        for sid, rel in (v.get("images") or {}).items():
            _path(rel, f"variants[{i}].images[{sid}]", e)
    for i, s in enumerate(samples if isinstance(samples, list) else []):
        if not isinstance(s, dict) or not s.get("id"):
            e.append(f"samples[{i}] 缺少 id")
    if d.get("winner") and d["winner"] not in ids:
        e.append(f"winner={d['winner']!r} 不在 variants 的 id 里：{sorted(ids)}")
    if "compare" in d and not isinstance(d["compare"], list):
        e.append("compare 必须是数组")
    return e


def validate_manifest(data) -> list[str]:
    """返回中文错误列表；空列表表示可以被 workbench 正确渲染。"""
    if hasattr(data, "to_dict"):
        data = data.to_dict()
    if not isinstance(data, dict):
        return ["manifest 必须是 JSON 对象"]
    kind = str(data.get("kind") or "run")
    if kind == "experiment":
        return _check_experiment(data)
    return _check_run(data)


def validate_file(path) -> list[str]:
    p = Path(path)
    try:
        return validate_manifest(json.loads(p.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"读取/解析 {p} 失败：{exc}"]


def export(target: Path | None = None) -> list[Path]:
    """把 Python 里的 schema 导出成 .json，供前端 / Pydantic / CI 使用。"""
    out = Path(target) if target else _SCHEMA_DIR
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, schema in SCHEMA_FILES.items():
        p = out / name
        p.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(p)
    return written


if __name__ == "__main__":
    for p in export():
        print("[cv_engine.schema] 已导出", p)
