"""产物契约 —— 全组唯一权威的字段定义（仅标准库，零 Web / 零 CV 依赖）。

谁读这份文件：
    C / D  写 stages 时 import 这里的类型，不要手写 manifest 字段
    B      server/schemas.py 的 Pydantic 模型对齐这里
    E      evaluation 直接读 manifest.json
    workbench  只读 manifest.json，字段名硬编码在 partitions/*.yaml

三条铁律：
    1. manifest.json 只能由 writer.RunWriter / ExperimentWriter 产出。
    2. 字段名以本文件为准；改名必须同步 workbench/partitions/*.yaml 并升 SCHEMA_VERSION。
    3. 所有产物路径相对 run 目录，禁止绝对路径与 '..'（见 safe_rel）。
"""
from __future__ import annotations

import dataclasses
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

SCHEMA_VERSION = "1.0"

STAGE_NAMES: dict[str, str] = {
    "01": "抽帧与质量筛选",
    "02": "白板区域定位",
    "03": "教师行为与遮挡",
    "04": "变化检测与门控",
    "05": "板书增强与快照",
    "06": "文字识别",
    "07": "板书条目与证据",
    "08": "课堂笔记",
    "09": "运行统计",
}
STAGE_IDS = tuple(STAGE_NAMES)

# stages.<no>.metrics.* 的键被 workbench/partitions/*.yaml 硬编码，改动需同步。
METRIC_KEYS: dict[str, tuple[str, ...]] = {
    "01": ("sampled", "blur_dropped"),
    "02": ("located", "confidence"),
    "03": ("pose_frames", "occluded"),
    "04": ("passed", "pass_rate"),
    "05": ("snapshots", "clarity"),
    "06": ("calls", "boxes", "score"),
    "08": ("sections", "chars"),
    "09": ("elapsed_s", "mem_mb"),
}
# 逐阶段数据表 / 文本（同样硬编码在 YAML）。
TABLE_PATHS: dict[str, str] = {
    "01": "01_frames/frames.json",
    "04": "04_gate/gate.json",
    "06": "06_ocr/calls.json",
    "08": "08_notes/notes.md",
    "09": "09_stats/summary.json",
}
# 真实中间产物图片放这里，workbench 的 glob 自动收录。
MEDIA_DIRS = tuple(f"media/{no}_{name}" for no, name in (
    ("01", "frames"), ("02", "board"), ("03", "pose"), ("04", "gate"),
    ("05", "enhance"), ("06", "ocr"), ("07", "items"), ("08", "notes"),
    ("09", "stats"),
))


class StageStatus(str, Enum):
    """阶段 / 条目在页签上的三态；其它值会被工作台当成 pending 显示。"""
    DONE = "done"
    RUNNING = "running"
    PENDING = "pending"


class RunStatus(str, Enum):
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class PageKind(str, Enum):
    RUN = "run"
    EXPERIMENT = "experiment"


STAGE_STATUS_VALUES = tuple(s.value for s in StageStatus)
RUN_STATUS_VALUES = tuple(s.value for s in RunStatus)


def safe_rel(rel: str) -> str:
    """产物路径统一校验：相对 run 目录、无 '..'、无盘符、非空。"""
    if not isinstance(rel, str) or not rel.strip():
        raise ValueError("产物路径不能为空")
    p = PurePosixPath(rel.strip().replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or ":" in p.parts[0]:
        raise ValueError(f"产物路径必须相对 run 目录且不含 '..'：{rel!r}")
    return p.as_posix()


def _val(x: Any) -> Any:
    """str-Enum 在 3.11+ 的 str() 会返回 'StageStatus.DONE'，必须显式取 .value。"""
    return x.value if isinstance(x, Enum) else x


def _plain(obj: Any) -> Any:
    """asdict → JSON 安全结构；enum 取值、None 省略、extra 平铺回顶层。"""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        out = {}
        extra = obj.get("_extra")          # 用下划线前缀，避免误伤 metrics 里的普通键
        for k, v in obj.items():
            if k == "_extra" or v is None:
                continue
            out[k] = _plain(v)
        if isinstance(extra, dict):
            for k, v in extra.items():
                if v is not None and k not in out:
                    out[k] = _plain(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


@dataclass
class _Record:
    """所有契约记录的基类：_extra 保存未知字段，保证新旧版本互不丢数据。"""
    _extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict:
        return _plain(asdict(self))

    @classmethod
    def from_dict(cls, data: dict | None) -> "_Record":
        return _from_record(cls, data)


# --- 嵌套类型（按字段名映射，from_dict 用它还原 dataclass） ---
_NESTED: dict[str, Any] = {}


def _from_record(cls, data: dict | None):
    data = dict(data or {})
    names = {f.name for f in fields(cls)}
    known: dict[str, Any] = {}
    unknown: dict[str, Any] = {}
    for k, v in data.items():
        if k not in names:
            unknown[k] = v
            continue
        spec = _NESTED.get(k)
        if spec is not None and v is not None:
            if isinstance(spec, tuple):  # ("dict"|"list", 子类型)
                shape, sub = spec
                if shape == "dict" and isinstance(v, dict):
                    v = {kk: _from_record(sub, vv) for kk, vv in v.items()}
                elif shape == "list" and isinstance(v, list):
                    v = [_from_record(sub, x) for x in v]
            elif isinstance(v, dict):
                v = _from_record(spec, v)
        known[k] = v
    obj = cls(**known)
    if unknown:
        obj._extra = unknown
    return obj


@dataclass
class VideoMeta(_Record):
    name: str = ""
    frames: int = 0
    fps: float = 0.0
    duration_s: float = 0.0          # 不是 duration_sec
    width: int = 0
    height: int = 0


@dataclass
class StageResult(_Record):
    """stages 字典里的值；stage_id 就是字典的键，不重复写进值里。"""
    name: str = ""
    status: str = StageStatus.PENDING.value
    metrics: dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    note: str = ""


@dataclass
class OcrBox(_Record):
    text: str = ""
    poly: list[list[int]] = field(default_factory=list)   # 四点多边形，不丢几何
    score: float = 0.0
    frame: int = 0                   # 原始视频帧号
    ts: float = 0.0                  # 秒
    ocr_call: int = 0


@dataclass
class BoardItem(_Record):
    """07 条目。frame/crop 是相对 run 目录的图片路径，工作台直接渲染。"""
    item_id: str = ""
    text: str = ""                   # 最佳版本原文
    first_seen_sec: float = 0.0
    last_seen_sec: float = 0.0
    frame: str = ""
    crop: str = ""
    ocr_link: str = ""               # 指向 06 OCR 页，如 "#06"
    status: str = StageStatus.DONE.value
    # 以下是评测 / 可核验用的超集字段，工作台忽略。
    bbox: list[int] | None = None
    best: OcrBox | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    archived: bool = False           # 擦除后归档，不覆盖原文


@dataclass
class FileEntry(_Record):
    path: str = ""
    size: str = ""                   # 展示用，如 "610 KB"；也可给字节数


@dataclass
class RunManifest(_Record):
    """一次完整流水线。缺省 kind=run，workbench 完全按这个形状读。"""
    schema_version: str = SCHEMA_VERSION
    kind: str = PageKind.RUN.value
    run_id: str = ""
    title: str = ""
    created_at: str = ""
    status: str = RunStatus.RUNNING.value
    video: VideoMeta = field(default_factory=VideoMeta)
    config: dict[str, Any] = field(default_factory=dict)
    stages: dict[str, StageResult] = field(default_factory=dict)
    items: list[BoardItem] = field(default_factory=list)
    compare: list[dict[str, Any]] = field(default_factory=list)
    files: list[FileEntry] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def stage(self, no: str) -> StageResult | None:
        return self.stages.get(str(no).zfill(2))

    def set_stage(self, no: str, *, status: str | None = None,
                  metrics: dict | None = None, name: str | None = None,
                  duration_s: float | None = None, note: str | None = None) -> StageResult:
        key = str(no).zfill(2)
        st = self.stages.setdefault(key, StageResult(name=STAGE_NAMES.get(key, "")))
        if status is not None:
            st.status = str(_val(status))
        if metrics:
            st.metrics.update(metrics)
        if name is not None:
            st.name = name
        if duration_s is not None:
            st.duration_s = duration_s
        if note is not None:
            st.note = note
        return st


# --- 实验页（kind=experiment）---

@dataclass
class Sample(_Record):
    id: str = ""
    title: str = ""


@dataclass
class Variant(_Record):
    id: str = ""
    name: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    images: dict[str, str] = field(default_factory=dict)      # 样本 id → 图片相对路径
    captions: dict[str, str] = field(default_factory=dict)    # 样本 id → 图注


@dataclass
class ExperimentManifest(_Record):
    """单阶段调参实验。列=变体、行=同一样本；允许一天多次、允许删。"""
    schema_version: str = SCHEMA_VERSION
    kind: str = PageKind.EXPERIMENT.value
    run_id: str = ""
    title: str = ""
    created_at: str = ""
    stage: str = ""
    stage_name: str = ""
    input: str = ""
    winner: str = ""
    samples: list[Sample] = field(default_factory=list)
    variants: list[Variant] = field(default_factory=list)
    compare: list[dict[str, Any]] = field(default_factory=list)


_NESTED.update({
    "video": VideoMeta,
    "best": OcrBox,
    "stages": ("dict", StageResult),
    "items": ("list", BoardItem),
    "files": ("list", FileEntry),
    "samples": ("list", Sample),
    "variants": ("list", Variant),
})


def new_run(run_id: str, *, title: str = "", video: dict | None = None,
            config: dict | None = None) -> RunManifest:
    """工厂：9 个阶段全部初始化为 pending，供 writer 逐阶段更新。"""
    return RunManifest(
        run_id=run_id,
        title=title or f"板书数字化 · {run_id}",
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        video=VideoMeta.from_dict(video),          # type: ignore[assignment]
        config=dict(config or {}),
        stages={no: StageResult(name=name, status=StageStatus.PENDING.value)
                for no, name in STAGE_NAMES.items()},
    )


def new_experiment(exp_id: str, *, stage: str, title: str = "",
                   stage_name: str = "", input_desc: str = "") -> ExperimentManifest:
    return ExperimentManifest(
        run_id=exp_id,
        title=title or f"单阶段实验 · {exp_id}",
        created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        stage=str(stage).zfill(2),
        stage_name=stage_name or STAGE_NAMES.get(str(stage).zfill(2), ""),
        input=input_desc,
    )


def load_manifest(data: dict) -> RunManifest | ExperimentManifest:
    """按 kind 还原成对应 dataclass；缺省当 run，保证旧 manifest 永不失效。"""
    kind = str((data or {}).get("kind") or PageKind.RUN.value)
    cls = ExperimentManifest if kind == PageKind.EXPERIMENT.value else RunManifest
    return cls.from_dict(data)         # type: ignore[return-value]


__all__ = [
    "SCHEMA_VERSION", "STAGE_IDS", "STAGE_NAMES", "METRIC_KEYS", "TABLE_PATHS", "MEDIA_DIRS",
    "StageStatus", "RunStatus", "PageKind", "STAGE_STATUS_VALUES", "RUN_STATUS_VALUES",
    "safe_rel", "VideoMeta", "StageResult", "OcrBox", "BoardItem", "FileEntry",
    "RunManifest", "Sample", "Variant", "ExperimentManifest",
    "new_run", "new_experiment", "load_manifest",
]
