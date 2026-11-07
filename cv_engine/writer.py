"""唯一落盘口：所有 runs/<run_id>/ 与 experiments/<exp_id>/ 的内容都从这里写。

    with RunWriter("20261107_1432_C_zone", video={"frames": 9000, "duration_s": 300.0}) as w:
        w.begin_stage("01")
        w.write_json("01_frames/frames.json", rows)
        w.save_image("media/01_frames/sample_0000.jpg", bgr_frame)
        w.finish_stage("01", metrics={"sampled": 2236, "blur_dropped": 0})
        ...
        w.write_item(BoardItem(item_id="IT-001", text="...", frame=..., crop=...))
    # 退出时自动 finalize：扫描产物填 files[]、校验契约、写最终 manifest

设计约束：
    - manifest.json 每次都用「写 .tmp → os.replace」原子替换，--watch 不会读到半成品。
    - 所有相对路径过 contracts.safe_rel，杜绝 '..' 越出 run 目录。
    - cv_engine 不 import workbench / server / FastAPI；要重生成页面请外部调用 build.py 或 --watch。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from . import contracts as k

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNS = PROJECT_ROOT / "runs"
EXPERIMENTS = PROJECT_ROOT / "experiments"


def _human(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


class _WriterBase:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._closed = False

    # --- 底层写 ---
    def _atomic(self, rel: str, data: str | bytes) -> Path:
        p = self.root / k.safe_rel(rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        if isinstance(data, str):
            tmp.write_text(data, encoding="utf-8")
        else:
            tmp.write_bytes(data)
        os.replace(tmp, p)          # 原子替换：--watch 轮询时不会读到半截 JSON
        return p

    def write_text(self, rel: str, text: str) -> Path:
        return self._atomic(rel, text)

    def write_bytes(self, rel: str, data: bytes) -> Path:
        return self._atomic(rel, data)

    def write_json(self, rel: str, obj: Any) -> Path:
        return self._atomic(rel, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")

    def save_image(self, rel: str, image: Any) -> Path:
        """image 可以是编码后的 bytes，或 OpenCV / numpy 的 BGR 数组（按需 import cv2）。"""
        if isinstance(image, (bytes, bytearray, memoryview)):
            return self.write_bytes(rel, bytes(image))
        import cv2                          # 延迟导入：不用图片时可以完全不装 cv2
        ext = Path(rel).suffix or ".jpg"
        ok, buf = cv2.imencode(ext, image)
        if not ok:
            raise ValueError(f"无法编码图片 {rel!r}（后缀 {ext}）")
        return self.write_bytes(rel, buf.tobytes())

    def log(self, event: dict) -> None:
        """结构化日志（逐帧 / 逐次 OCR），追加一行 JSONL。"""
        with (self.root / "log.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def _flush_manifest(self) -> Path:
        return self._atomic("manifest.json",
                            json.dumps(self.manifest.to_dict(), ensure_ascii=False, indent=2) + "\n")

    def validate(self) -> list[str]:
        from .schema import validate_manifest       # 延迟导入，避免 python -m cv_engine.schema 的 runpy 警告
        return validate_manifest(self.manifest)


class RunWriter(_WriterBase):
    """一次完整流水线。构造时即写好 9 个 pending 阶段，之后逐阶段增量更新。"""

    def __init__(self, run_id: str, *, root: Path | str | None = None,
                 title: str = "", video: dict | None = None,
                 config: dict | None = None):
        super().__init__(Path(root) if root else RUNS / run_id)
        self.manifest = k.new_run(run_id, title=title, video=video, config=config)
        if config is not None:
            self.write_config(config)
        self._flush_manifest()

    def write_config(self, config: dict) -> Path:
        """参数快照。写成 JSON —— JSON 是 YAML 1.2 的子集，yaml.safe_load 能直接读。"""
        self.manifest.config = dict(config)
        p = self.write_text("config.yaml", json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        self._flush_manifest()
        return p

    def set_video(self, **fields) -> None:
        merged = {**self.manifest.video.to_dict(), **fields}
        self.manifest.video = k.VideoMeta.from_dict(merged)
        self._flush_manifest()

    # --- 阶段 ---
    def begin_stage(self, no: str) -> None:
        self.manifest.set_stage(no, status=k.StageStatus.RUNNING)
        self._flush_manifest()

    def finish_stage(self, no: str, *, metrics: dict | None = None,
                     duration_s: float | None = None, note: str | None = None) -> None:
        self.manifest.set_stage(no, status=k.StageStatus.DONE, metrics=metrics,
                                duration_s=duration_s, note=note)
        self._flush_manifest()

    def write_stage(self, no: str, *, status: str, metrics: dict | None = None,
                    **kw) -> None:
        """需要自定义状态时用；status 只接受三态。"""
        if status not in k.STAGE_STATUS_VALUES:
            raise ValueError(f"status 必须是 {k.STAGE_STATUS_VALUES}，收到 {status!r}")
        self.manifest.set_stage(no, status=status, metrics=metrics, **kw)
        self._flush_manifest()

    def fail_stage(self, no: str, reason: str) -> None:
        """阶段失败：工作台没有 failed 色点，保留 running + 把原因写进 note / warnings。"""
        self.manifest.set_stage(no, note=reason)
        self.manifest.status = k.RunStatus.FAILED.value
        self.warn(f"阶段 {no} 失败：{reason}")
        self._flush_manifest()

    # --- 条目 / 对照 / 告警 ---
    def write_item(self, item: k.BoardItem | dict) -> None:
        it = item if isinstance(item, k.BoardItem) else k.BoardItem.from_dict(item)
        for f in (it.frame, it.crop, *it.evidence.values()):
            if f:
                k.safe_rel(f)
        self.manifest.items.append(it)
        self._flush_manifest()

    add_item = write_item

    def set_compare(self, rows: list[dict]) -> None:
        self.manifest.compare = list(rows)
        self._flush_manifest()

    def set_outputs(self, outputs: dict[str, str]) -> None:
        for rel in outputs.values():
            k.safe_rel(rel)
        self.manifest.outputs = dict(outputs)
        self._flush_manifest()

    def warn(self, msg: str) -> None:
        if msg not in self.manifest.warnings:
            self.manifest.warnings.append(msg)
        self._flush_manifest()

    # --- 产物索引 / 收尾 ---
    def refresh_files(self) -> None:
        """扫描真实落盘文件填 files[]；显式 add_file 的条目优先。"""
        explicit = {f.path: f for f in self.manifest.files}
        skip = {"manifest.json", "index.html"}
        for p in sorted(self.root.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(self.root).as_posix()
            if (rel in skip or p.suffix == ".tmp" or rel.startswith("_modes/")
                    or rel.startswith(".")):
                continue
            explicit.setdefault(rel, k.FileEntry(path=rel, size=_human(p.stat().st_size)))
        self.manifest.files = [explicit[key] for key in sorted(explicit)]

    def add_file(self, path: str, size: str | None = None) -> None:
        rel = k.safe_rel(path)
        if size is None:
            p = self.root / rel
            size = _human(p.stat().st_size) if p.is_file() else "—"
        self.manifest.files = [f for f in self.manifest.files if f.path != rel]
        self.manifest.files.append(k.FileEntry(path=rel, size=size))

    def finalize(self, *, status: str = k.RunStatus.DONE.value, scan: bool = True) -> dict:
        if status not in k.RUN_STATUS_VALUES:
            raise ValueError(f"status 必须是 {k.RUN_STATUS_VALUES}")
        self.manifest.status = status
        if scan:
            self.refresh_files()
        errors = self.validate()
        for err in errors:
            self.manifest.warnings.append(f"契约校验：{err}")
        path = self._flush_manifest()
        self._closed = True
        return {"path": path, "errors": errors, "files": len(self.manifest.files),
                "warnings": list(self.manifest.warnings)}

    def __enter__(self) -> "RunWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.manifest.status = k.RunStatus.FAILED.value
            self.warn(f"运行异常：{exc_type.__name__}: {exc}")
        elif not self._closed:
            self.finalize()
        return False            # 不吞异常


class ExperimentWriter(_WriterBase):
    """单阶段调参实验。列=变体 / 行=同一样本，产物在 experiments/<exp_id>/。"""

    def __init__(self, exp_id: str, *, stage: str, root: Path | str | None = None,
                 title: str = "", stage_name: str = "", input_desc: str = ""):
        super().__init__(Path(root) if root else EXPERIMENTS / exp_id)
        self.manifest = k.new_experiment(exp_id, stage=stage, title=title,
                                         stage_name=stage_name, input_desc=input_desc)
        self._flush_manifest()

    def add_sample(self, sid: str, title: str = "") -> None:
        self.manifest.samples.append(k.Sample(id=str(sid), title=title))
        self._flush_manifest()

    def add_variant(self, vid: str, *, name: str = "", params: dict | None = None,
                    images: dict[str, str] | None = None,
                    captions: dict[str, str] | None = None) -> None:
        for rel in (images or {}).values():
            if rel:
                k.safe_rel(rel)
        self.manifest.variants.append(k.Variant(
            id=str(vid), name=name or str(vid), params=dict(params or {}),
            images=dict(images or {}), captions=dict(captions or {})))
        self._flush_manifest()

    def set_winner(self, vid: str) -> None:
        self.manifest.winner = str(vid)
        self._flush_manifest()

    def set_compare(self, rows: list[dict]) -> None:
        self.manifest.compare = list(rows)
        self._flush_manifest()

    def finalize(self) -> dict:
        errors = self.validate()
        path = self._flush_manifest()
        self._closed = True
        return {"path": path, "errors": errors}

    def __enter__(self) -> "ExperimentWriter":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None and not self._closed:
            self.finalize()
        return False


__all__ = ["RunWriter", "ExperimentWriter", "RUNS", "EXPERIMENTS"]
