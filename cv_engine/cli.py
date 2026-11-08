"""视频算法最小闭环 CLI。"""
import argparse
from datetime import datetime
from pathlib import Path
import sys

from .config import PipelineConfig


def main(argv=None):
    parser = argparse.ArgumentParser(description="视频 → 抽帧 → 人工标定/全帧 → 增强 → OCR → 原文笔记")
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--config", type=Path, help="YAML 配置；命令行参数优先")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--start", type=float, dest="start_s")
    parser.add_argument("--end", type=float, dest="end_s")
    parser.add_argument("--interval", type=float, dest="sample_interval_s")
    parser.add_argument("--max-frames", type=int)
    parser.add_argument("--roi", type=int, nargs=4, metavar=("X", "Y", "W", "H"))
    parser.add_argument("--enhance", choices=["clahe", "none"])
    args = parser.parse_args(argv)
    try:
        data = {}
        if args.config:
            import yaml
            data = yaml.safe_load(args.config.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("配置文件须为 YAML 对象")
        for key in ("start_s", "end_s", "sample_interval_s", "max_frames", "roi", "enhance"):
            value = getattr(args, key)
            if value is not None:
                data[key] = value
        config = PipelineConfig(**data).validate()
        if not args.video.is_file():
            raise ValueError(f"视频文件不存在：{args.video}")
        run_id = args.run_id or datetime.now().strftime("%Y%m%d_%H%M%S_%f_minimal")
        from .contracts import safe_rel
        if safe_rel(run_id) != run_id or "/" in run_id or run_id == ".":
            raise ValueError("run-id 必须是单个目录名")
        from .writer import RUNS, RunWriter
        root = RUNS / run_id
        # 避免旧产物混入本次 manifest；不自动覆盖已有结果。
        root.mkdir(parents=True, exist_ok=False)
        from .pipeline import run
        writer = RunWriter(run_id, root=root, title="算法最小闭环 · " + args.video.stem)
        result = run(args.video.resolve(), config, writer)
    except (ValueError, TypeError, OSError, RuntimeError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(f"完成：{result['path']}，{result['files']} 个产物")
    print(f"生成工作台：pixi run python -m workbench.build --run {run_id} --assets inline")
    return 0
