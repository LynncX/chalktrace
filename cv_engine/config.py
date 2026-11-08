"""最小流水线配置；参数快照由 RunWriter 保存。"""
from dataclasses import asdict, dataclass
import math


@dataclass
class PipelineConfig:
    start_s: float = 0.0
    end_s: float | None = None  # 半开区间 [start_s, end_s)
    sample_interval_s: float = 5.0
    max_frames: int = 3  # 候选采样上限，避免默认对长视频执行大量 OCR
    blur_min: float = 0.0  # 默认不丢帧；阈值必须通过素材校准
    roi: list[int] | None = None  # 原图像素 x, y, width, height
    corners: list[list[float]] | None = None  # 左上、右上、右下、左下
    enhance: str = "clahe"  # clahe 或 none，供基线对照
    det_model: str = "PP-OCRv5_server_det"
    rec_model: str = "PP-OCRv5_server_rec"
    score_min: float = 0.0  # 保留低置信度原文供核验
    cpu_threads: int = 4

    def validate(self):
        for name in ("start_s", "sample_interval_s", "blur_min", "score_min"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{name} 必须是有限数值")
        if self.start_s < 0 or self.sample_interval_s <= 0 or self.blur_min < 0:
            raise ValueError("起点和模糊阈值必须非负，采样间隔必须大于 0")
        if self.end_s is not None and (isinstance(self.end_s, bool) or
                not isinstance(self.end_s, (int, float)) or not math.isfinite(self.end_s) or self.end_s <= self.start_s):
            raise ValueError("end_s 必须是大于 start_s 的有限数值")
        for name in ("max_frames", "cpu_threads"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} 必须是正整数")
        if not 0 <= self.score_min <= 1 or self.enhance not in ("clahe", "none"):
            raise ValueError("score_min 须在 [0, 1]，enhance 须为 clahe 或 none")
        if self.roi is not None and self.corners is not None:
            raise ValueError("roi 与 corners 只能选择一个")
        for name in ("det_model", "rec_model"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} 不能为空")
        return self

    def to_dict(self):
        return asdict(self)
