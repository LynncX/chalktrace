#!/usr/bin/env python3
"""2026-11-08：验证本项目 CPU OCR 环境，保留真实单帧与识别结果。

用法：pixi run ocr-smoke --seconds 120
只验证抽帧、检测和识别；其余阶段保持 pending，不代表完整流水线。
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=ROOT / "data/videos/test_video.mp4")
    parser.add_argument("--seconds", type=float, default=120.0, help="抽取时间点（秒）")
    parser.add_argument("--run-id", default="ocr_smoke", help="产物目录名")
    args = parser.parse_args()
    if args.seconds < 0 or Path(args.run_id).name != args.run_id or args.run_id in (".", ".."):
        parser.error("时间点必须非负，run-id 必须是单个目录名")

    for key, folder in {
        "PADDLE_PDX_CACHE_HOME": "paddlex", "PADDLE_HOME": "paddle",
        "PADDLEOCR_HOME": "paddleocr", "HF_HOME": "huggingface",
    }.items():
        os.environ.setdefault(key, str(ROOT / ".cache" / folder))
    os.environ.setdefault("XDG_CACHE_HOME", str(ROOT / ".cache"))

    import cv2
    from paddleocr import PaddleOCR
    from cv_engine import RunWriter

    cap = cv2.VideoCapture(str(args.video))
    try:
        if not cap.isOpened():
            raise RuntimeError(f"无法打开视频：{args.video}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_MSEC, args.seconds * 1000)
        ok, frame = cap.read()
        if not ok:
            raise RuntimeError(f"无法解码 {args.seconds}s 处的帧")
        actual_frame = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
        timestamp = actual_frame / fps
    finally:
        cap.release()

    config = {"device": "cpu", "det": "PP-OCRv5_server_det",
              "rec": "PP-OCRv5_server_rec", "seconds": timestamp}
    with RunWriter(args.run_id, title="OCR 冒烟测试（单帧，非完整流水线）", config=config) as writer:
        writer.set_video(name=args.video.name, fps=fps, frames=frames,
                         duration_s=frames / fps, width=frame.shape[1], height=frame.shape[0])
        writer.begin_stage("01")
        source = "media/01_frames/source.jpg"
        writer.save_image(source, frame)
        writer.write_json("01_frames/frames.json", [{"frame": actual_frame, "ts": timestamp}])
        writer.finish_stage("01", metrics={"sampled": 1, "blur_dropped": 0})
        writer.begin_stage("06")
        start = time.perf_counter()
        engine = PaddleOCR(
            text_detection_model_name=config["det"],
            text_recognition_model_name=config["rec"],
            use_doc_orientation_classify=False, use_doc_unwarping=False,
            use_textline_orientation=False, device="cpu", cpu_threads=4,
            enable_mkldnn=False,
        )
        load_s = time.perf_counter() - start
        start = time.perf_counter()
        result = list(engine.predict(frame))[0]
        predict_s = time.perf_counter() - start
        texts = list(result["rec_texts"])
        scores = [float(score) for score in result["rec_scores"]]
        boxes = [{"text": text, "score": score, "poly": poly.tolist(),
                  "frame": actual_frame, "ts": timestamp}
                 for text, score, poly in zip(texts, scores, result["rec_polys"])]
        if not boxes:
            raise RuntimeError("推理完成但无识别文本；请更换视频时间点")
        writer.write_json("06_ocr/boxes.json", boxes)
        writer.write_json("06_ocr/calls.json", [{"call": 1, "frame": actual_frame,
                          "ts": timestamp, "text": "\n".join(texts),
                          "score": sum(scores) / len(scores),
                          "boxes": len(boxes), "elapsed_s": predict_s}])
        overlay = frame.copy()
        for index, box in enumerate(boxes):
            poly = result["rec_polys"][index].astype("int32")
            cv2.polylines(overlay, [poly], True, (0, 200, 255), 2)
            cv2.putText(overlay, str(index + 1), tuple(poly[0]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        writer.save_image("media/06_ocr/overlay_0001.png", overlay)
        writer.save_image("media/06_ocr/original_0001.jpg", frame)
        writer.write_text("06_ocr/text.txt", "\n".join(texts) + "\n")
        writer.finish_stage("06", metrics={"calls": 1, "boxes": len(boxes),
                            "score": sum(scores) / len(scores)}, duration_s=predict_s)
        writer.warn("单帧环境冒烟测试；未执行定位、增强、门控、条目跟踪和笔记生成。")
        writer.write_json("smoke_summary.json", {"config": config, "load_s": load_s,
                          "predict_s": predict_s, "boxes": len(boxes)})
        summary = writer.finalize()
        if summary["errors"]:
            raise RuntimeError(str(summary["errors"]))
    print(f"PASS: {len(boxes)} 个文本框；初始化 {load_s:.2f}s；推理 {predict_s:.2f}s", flush=True)
    print(f"产物：runs/{args.run_id}/", flush=True)
    for index, text in enumerate(texts[:8], 1):
        print(f"{index}: {text}")


if __name__ == "__main__":
    main()
