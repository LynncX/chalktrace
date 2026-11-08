#!/usr/bin/env python3
"""2026-11-08：同视频同配置比较固定采样与遮挡/变化门控，保存真实逐帧证据。

用法：pixi run python scripts/compare_gate.py --video data/videos/test_video.mp4 \
    --config evaluation/configs/gate_test_video.yaml
比较调用成本与跳过原因；没有人工标注时不声称 CER 或召回改善。
"""
import argparse
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--prefix", default=datetime.now().strftime("%Y%m%d_%H%M%S_%f"))
    args = parser.parse_args()
    import cv2
    import yaml
    from cv_engine.config import PipelineConfig
    from cv_engine.contracts import safe_rel
    from cv_engine.pipeline import run, read_image
    from cv_engine.stages.s04_gate import gate_overlay
    from cv_engine.writer import RunWriter, ExperimentWriter
    from workbench.build import build

    if safe_rel(args.prefix) != args.prefix or "/" in args.prefix or args.prefix == ".":
        parser.error("prefix 必须是单个目录名")
    if not args.video.is_file():
        parser.error("视频不存在")
    config = PipelineConfig(**yaml.safe_load(args.config.read_text(encoding="utf-8"))).validate()
    ids = {"fixed": args.prefix + "_fixed", "gated": args.prefix + "_gated"}
    experiment_id = args.prefix + "_comparison"
    for path in ([ROOT / "runs" / run_id for run_id in ids.values()] + [ROOT / "experiments" / experiment_id]):
        if path.exists():
            parser.error(f"目录已存在：{path}")
    results = {}
    for mode, gate_mode in (("fixed", "fixed"), ("gated", "occlusion_change")):
        writer = RunWriter(ids[mode], title=f"门控对比 · {mode}")
        run(args.video.resolve(), replace(config, gate_mode=gate_mode), writer)
        results[mode] = writer
        build(str(writer.root), assets_mode="inline")

    fixed, gated = results["fixed"], results["gated"]
    gates = json.loads((gated.root / "04_gate/gate.json").read_text())
    fixed_calls = json.loads((fixed.root / "06_ocr/calls.json").read_text())
    gate_calls = json.loads((gated.root / "06_ocr/calls.json").read_text())
    frame_sets = [json.loads((writer.root / "01_frames/frames.json").read_text()) for writer in (fixed, gated)]
    if frame_sets[0] != frame_sets[1]:
        raise RuntimeError("两组采样帧不一致，不能生成对照结论")
    by_frame = {row["frame"]: row for row in gates}
    rows = []
    for name, calls, writer in (("固定采样", fixed_calls, fixed), ("遮挡+变化门控", gate_calls, gated)):
        rows.append({"配置": name, "候选帧": len(gates), "OCR 调用": len(calls),
                     "高覆盖帧 OCR": sum(by_frame[c["frame"]]["occlusion"] > config.occlusion_max for c in calls),
                     "推理耗时/s": round(sum(c["elapsed_s"] for c in calls), 3),
                     "总耗时/s": round(writer.manifest.stage("09").metrics["elapsed_s"], 3),
                     "识别框": writer.manifest.stage("06").metrics["boxes"],
                     "CER/召回": "未标注，未计算"})
    reasons = {reason: sum(row["reason"] == reason for row in gates) for reason in sorted({r["reason"] for r in gates})}
    with ExperimentWriter(experiment_id, stage="04", title="固定采样 vs 遮挡与变化门控",
                          stage_name="变化门控", input_desc="同视频、采样、标定、增强和 OCR；仅 gate_mode 不同") as experiment:
        images = {"fixed": {}, "gated": {}}
        captions = {"fixed": {}, "gated": {}}
        for row in gates:
            key = str(row["frame"])
            experiment.add_sample(key, f"{row['ts']:.2f}s · 帧 {key}")
            fixed_board = read_image(fixed.root / f"media/02_board/board_{row['frame']:08d}.png")
            baseline_info = dict(row, fired=True, reason="fixed_sampling")
            for variant, image in (("fixed", gate_overlay(fixed_board, baseline_info)),
                                   ("gated", read_image(gated.root / row["audit_path"]))):
                path = f"media/{variant}_{key}.jpg"
                experiment.save_image(path, image)
                images[variant][key] = path
            captions["fixed"][key] = "执行 OCR · 固定采样"
            captions["gated"][key] = ("执行 OCR · " if row["fired"] else "跳过 · ") + row["reason_text"]
        for variant, label in (("fixed", "固定采样"), ("gated", "遮挡+变化门控")):
            experiment.add_variant(variant, name=label, params={"run_id": ids[variant]},
                                   images=images[variant], captions=captions[variant])
        experiment.set_compare(rows)
        summary = {"runs": ids, "metrics": rows, "reasons": reasons,
                   "saved_calls": len(fixed_calls) - len(gate_calls),
                   "thresholds": config.to_dict(), "quality": "无人工标注，不计算或推断识别精度/召回"}
        experiment.write_json("summary.json", summary)
        result = experiment.finalize()
        if result["errors"]:
            raise RuntimeError(str(result["errors"]))
    build(str(experiment.root), assets_mode="inline")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"对照页面：experiments/{experiment_id}/index.html")


if __name__ == "__main__":
    main()
