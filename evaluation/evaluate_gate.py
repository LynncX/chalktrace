#!/usr/bin/env python3
"""2026-11-08：验证已人工标注的真实帧对，保存参考/候选证据与决策。

用法：pixi run python -m evaluation.evaluate_gate \
    --cases evaluation/annotations/gate_pairs.yaml --experiment gate_pairs_v1
这是变化组件的策略回放，假定参考图已完成 OCR；不执行/计数实际 OCR。
"""
import argparse
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import yaml

from cv_engine.config import PipelineConfig
from cv_engine.contracts import safe_rel
from cv_engine.stages.s02_board import locate_board
from cv_engine.stages.s04_gate import ChangeGate
from cv_engine.writer import EXPERIMENTS, ExperimentWriter


def validate_cases(document):
    if not isinstance(document, dict) or not isinstance(document.get("cases"), list) or not document["cases"]:
        raise ValueError("cases 文档必须包含非空样本列表")
    if not isinstance(document.get("video"), str) or not document["video"]:
        raise ValueError("video 必须是视频路径字符串")
    seen = set()
    for case in document["cases"]:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("每条样本须有字符串 id")
        if safe_rel(case["id"]) != case["id"] or "/" in case["id"] or case["id"] == "." or case["id"] in seen:
            raise ValueError("样本 id 必须是唯一目录名")
        seen.add(case["id"])
        if case.get("category") not in ("static", "added", "erase", "scene_change"):
            raise ValueError("未知的变化标注类型")
        if type(case.get("expected_fire")) is not bool:
            raise ValueError("expected_fire 必须是布尔标注")
        if case["expected_fire"] != (case["category"] != "static"):
            raise ValueError("变化类型与 expected_fire 标注冲突")
        if type(case.get("reference_s")) not in (int, float) or type(case.get("target_s")) not in (int, float):
            raise ValueError("帧时间必须是数值")
        if not np.isfinite([case["reference_s"], case["target_s"]]).all() or not 0 <= case["reference_s"] < case["target_s"]:
            raise ValueError("帧时间必须有限，且 0 <= reference_s < target_s")
        roi = case.get("roi")
        if not isinstance(roi, list) or len(roi) != 4 or any(type(v) is not int for v in roi) or min(roi[:2]) < 0 or min(roi[2:]) < 2:
            raise ValueError("roi 必须为非负起点与至少 2 像素宽高的四整数列表")
    return document


def read_video_frame(cap, seconds):
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame = round(seconds * fps)
    if fps <= 0 or frame >= cap.get(cv2.CAP_PROP_FRAME_COUNT):
        raise ValueError(f"时间 {seconds}s 超出视频或视频 FPS 无效")
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
    ok, image = cap.read()
    if not ok:
        raise RuntimeError(f"无法解码 {seconds}s 处的帧")
    actual = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
    return image, actual, actual / fps


def evaluate(cases_file, experiment_id):
    path = Path(cases_file).resolve()
    document = validate_cases(yaml.safe_load(path.read_text(encoding="utf-8")))
    config = PipelineConfig(**document.get("config", {})).validate()
    if config.gate_mode != "change":
        raise ValueError("本工具只验证无遮挡 ROI 的 change 组件")
    video = (path.parent / document["video"]).resolve()
    if safe_rel(experiment_id) != experiment_id or "/" in experiment_id or experiment_id == ".":
        raise ValueError("experiment 必须是目录名")
    root = EXPERIMENTS / experiment_id
    if root.exists():
        raise FileExistsError(f"输出目录已存在：{root}")
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        cap.release()
        raise ValueError(f"无法打开视频：{video}")
    try:
        with ExperimentWriter(experiment_id, root=root, stage="04", title="真实帧对 · 变化组件验证",
                              stage_name="变化验证", input_desc=document.get("description", "")) as writer:
            writer.write_json("annotations.json", document)
            rows, records = [], []
            images = {"reference": {}, "candidate": {}}
            captions = {"reference": {}, "candidate": {}}
            for case in document["cases"]:
                c = PipelineConfig(**{**config.to_dict(), "roi": case["roi"]}).validate()
                ref, ref_frame, ref_ts = read_video_frame(cap, case["reference_s"])
                current, frame, ts = read_video_frame(cap, case["target_s"])
                ref_board, _, ref_meta = locate_board(ref, c)
                board, _, meta = locate_board(current, c)
                if ref_board.shape != board.shape:
                    raise ValueError("帧对区域尺寸不一致")
                gate = ChangeGate(c)
                mask = np.zeros(board.shape[:2], dtype="uint8")
                gate.commit(ref_board, mask, ref_ts)  # 组件回放前提，不代表执行过真实 OCR
                info = gate.decide(board, mask, ts=ts, occlusion=0.0)
                passed = info["fired"] == case["expected_fire"]
                sid = case["id"]
                writer.add_sample(sid, case["note"])
                for variant, image, timestamp in (("reference", ref_board, ref_ts), ("candidate", board, ts)):
                    rel = f"media/{sid}_{variant}.png"
                    writer.save_image(rel, image)
                    images[variant][sid] = rel
                    captions[variant][sid] = (f"{timestamp:.3f}s · " + ("参考帧，假定已 OCR" if variant == "reference"
                                                 else ("策略放行" if info["fired"] else "策略跳过") + " · " + info["reason_text"]))
                rows.append({"样本": sid, "类型": case["category"], "预期": "放行" if case["expected_fire"] else "跳过",
                             "实际": "放行" if info["fired"] else "跳过", "SSIM": round(info["ssim"], 6) if info["ssim"] is not None else None,
                             "变化比例": round(info["change_ratio"], 6) if info["change_ratio"] is not None else None,
                             "符合标注": passed})
                records.append(dict(case=case, reference_frame=ref_frame, reference_ts=ref_ts,
                                    frame=frame, ts=ts, reference_calibration=ref_meta, calibration=meta,
                                    decision=info, passed=passed))
                print(sid, info["reason"], "PASS" if passed else "FAIL", flush=True)
            for vid, name in (("reference", "参考帧"), ("candidate", "候选帧与策略决策")):
                writer.add_variant(vid, name=name, images=images[vid], captions=captions[vid])
            writer.set_compare(rows)
            summary = {"kind": "component_policy_replay", "actual_ocr_calls": 0,
                       "count": len(records), "passed": sum(r["passed"] for r in records),
                       "missing_real_categories": document.get("missing_real_categories", []),
                       "config": config.to_dict(), "records": records}
            writer.write_json("summary.json", summary)
            result = writer.finalize()
            if result["errors"]:
                raise RuntimeError(str(result["errors"]))
    finally:
        cap.release()
    return summary, root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=Path("evaluation/annotations/gate_pairs.yaml"))
    parser.add_argument("--experiment", default=datetime.now().strftime("%Y%m%d_%H%M%S_%f_pairs"))
    args = parser.parse_args()
    summary, root = evaluate(args.cases, args.experiment)
    from workbench.build import build
    build(str(root), assets_mode="inline")
    print(f"标注吻合：{summary['passed']}/{summary['count']}；实际 OCR 调用：0（组件策略回放）")
    print(f"页面：{root / 'index.html'}")
    return 0 if summary["passed"] == summary["count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
