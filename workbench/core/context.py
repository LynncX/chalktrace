"""运行上下文：manifest 解析、路径定位、指标取值、缺失检测。

所有 tab 只通过 RunContext 读数据；不允许直接 open() 产物文件。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import assets


@dataclass
class Metric:
    label: str
    value: str
    unit: str = ""
    hint: str = ""


class RunContext:
    def __init__(self, root: Path, *, assets_mode: str = "tiered", out_dir: Path | None = None):
        self.root = Path(root).resolve()
        self.assets_mode = assets.normalize_mode(assets_mode)
        self.out_dir = Path(out_dir).resolve() if out_dir else self.root
        self.warnings: list[str] = []
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        p = self.root / "manifest.json"
        if not p.is_file():
            self.warnings.append(f"缺少 manifest.json：{p}")
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self.warnings.append(f"manifest.json 解析失败：{exc}")
            return {}

    # --- 路径 ---
    def path(self, rel: str) -> Path:
        return (self.root / rel).resolve()

    def asset(self, path: str, **kw) -> assets.ResolvedAsset:
        r = assets.resolve(self, assets.Asset(path, **kw),
                           mode=self.assets_mode, out_dir=self.out_dir)
        self.warnings.extend(r.warnings)
        return r

    # --- 数据 ---
    def get(self, key: str, default=None):
        """点号路径取值，支持 `items|len` 这类后缀。"""
        if not key:
            return default
        suffix = ""
        if "|" in key:
            key, suffix = key.split("|", 1)
        cur = self.manifest
        for part in str(key).split("."):
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, list) and part.isdigit():
                cur = cur[int(part)] if int(part) < len(cur) else None
            else:
                return default
            if cur is None:
                return default
        if suffix == "len" and isinstance(cur, (list, dict, str)):
            return len(cur)
        return cur

    def read_json(self, rel: str):
        p = self.path(rel)
        if not p.is_file():
            self.warnings.append(f"数据表缺失：{rel}")
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.warnings.append(f"数据表解析失败：{rel}")
            return []

    def resolve_metric(self, spec: dict) -> Metric:
        raw = self.get(str(spec.get("key", "")), default=None)
        if raw is None:
            value = "—"
        elif isinstance(raw, float):
            value = f"{raw:,.2f}".rstrip("0").rstrip(".")
        elif isinstance(raw, int):
            value = f"{raw:,}"
        else:
            value = str(raw)
        return Metric(
            label=str(spec.get("label", "")),
            value=value,
            unit=str(spec.get("unit", "")),
            hint=str(spec.get("hint", "")),
        )

    def status_of(self, no: str) -> str:
        stage = (self.manifest.get("stages") or {}).get(str(no)) or {}
        return str(stage.get("status", "pending"))

    # --- 输出 ---
    def public_payload(self, tabs: list | None = None) -> dict:
        return {
            "run_id": self.manifest.get("run_id", self.root.name),
            "assets_mode": self.assets_mode,
            "tabs": [{"no": t.no, "name": t.name, "short": t.short} for t in (tabs or [])],
            "items": self.manifest.get("items", []),
            "warnings": self.warnings,
        }

    def write(self, html: str, name: str = "index.html") -> Path:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        out = self.out_dir / name
        out.write_text(html, encoding="utf-8")
        return out
