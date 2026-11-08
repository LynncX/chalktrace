"""顺序编排最小流水线；不依赖 Web 或工作展示台。"""
from contextlib import contextmanager
from pathlib import Path
import resource
import re
import time

import cv2
import numpy as np

from .adapters.ocr import OcrEngine
from .config import PipelineConfig
from .stages.s01_frames import blur_score, extract_frames
from .stages.s02_board import locate_board
from .stages.s05_enhance import enhance_board


def read_image(path):
    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError(f"无法读取产物图像：{path}")
    return image


def run(video_path, config: PipelineConfig, writer, *, engine_factory=OcrEngine):
    """writer 由调用方提供；engine_factory 便于无模型验证编排与坐标回溯。"""
    config.validate()
    video_path = Path(video_path)
    started = time.perf_counter()
    timings = []
    records = []

    @contextmanager
    def stage(no):
        writer.begin_stage(no)
        start = time.perf_counter()
        print(f"[{no}] 开始", flush=True)
        try:
            yield
        except Exception as exc:
            writer.fail_stage(no, str(exc))
            raise
        else:
            seconds = time.perf_counter() - start
            writer.finish_stage(no, duration_s=seconds)
            timings.append(dict(stage=no, seconds=seconds, frames=len(records),
                                note=writer.manifest.stage(no).note))
            print(f"[{no}] 完成 {seconds:.2f}s", flush=True)

    with writer:
        writer.write_config(config.to_dict())
        writer.warn("最小闭环：未执行教师姿态、变化门控与跨帧条目跟踪；笔记仅为逐帧 OCR 原文。")
        with stage("01"):
            sampled, records = extract_frames(video_path, config, writer)
            writer.finish_stage("01", metrics={"sampled": len(sampled),
                                "blur_dropped": len(sampled) - len(records)},
                                note=f"固定间隔 {config.sample_interval_s}s；候选上限 {config.max_frames}")

        with stage("02"):
            board_rows = []
            for row in records:
                key = f"{row['frame']:08d}"
                board, overlay, meta = locate_board(read_image(writer.root / row["path"]), config)
                row.update(board=f"media/02_board/board_{key}.png", calibration=meta)
                writer.save_image(row["board"], board)
                overlay_path = f"media/02_board/calib_{key}.png"
                writer.save_image(overlay_path, overlay)
                board_rows.append(dict(frame=row["frame"], ts=row["ts"], path=row["board"],
                                       source_path=row["path"], overlay_path=overlay_path, **meta))
            writer.write_json("02_board/calibration.json", board_rows)
            mode = board_rows[0]["mode"]
            writer.finish_stage("02", metrics={"located": len(records) if mode != "full_frame" else 0,
                                               "processed": len(records)}, note=mode)
            if mode == "full_frame":
                writer.warn("未提供 ROI/四角标定，02 使用全帧直通；不代表自动定位成功。")

        with stage("05"):
            clarity = []
            for row in records:
                key = f"{row['frame']:08d}"
                board = read_image(writer.root / row["board"])
                enhanced = enhance_board(board, config.enhance)
                row["enhanced"] = f"media/05_enhance/enhanced_{key}.png"
                writer.save_image(f"media/05_enhance/f_{key}_color.jpg", board)
                writer.save_image(row["enhanced"], enhanced)
                clarity.append(blur_score(enhanced))
            writer.finish_stage("05", metrics={"snapshots": len(records),
                                "clarity": sum(clarity) / len(clarity)}, note=config.enhance)

        with stage("06"):
            load_start = time.perf_counter()
            engine = engine_factory(config)
            load_s = time.perf_counter() - load_start
            calls, all_boxes, scores = [], [], []
            for call, row in enumerate(records, 1):
                key = f"{row['frame']:08d}"
                start = time.perf_counter()
                boxes = engine.recognize(read_image(writer.root / row["enhanced"]),
                                         frame=row["frame"], ts=row["ts"], call=call)
                elapsed = time.perf_counter() - start
                source = read_image(writer.root / row["path"])
                overlay = source.copy()
                inverse = np.linalg.inv(np.asarray(row["calibration"]["source_to_board"]))
                for index, box in enumerate(boxes, 1):
                    poly = np.asarray(box.poly, dtype=np.float32).reshape(1, -1, 2)
                    source_poly = cv2.perspectiveTransform(poly, inverse)[0]
                    entry = box.to_dict()
                    entry.update(source_poly=source_poly.tolist(), poly_space="board",
                                 input_path=row["enhanced"], source_path=row["path"])
                    all_boxes.append(entry)
                    scores.append(box.score)
                    outline = np.rint(source_poly).astype("int32")
                    cv2.polylines(overlay, [outline], True, (0, 200, 255), 2)
                    cv2.putText(overlay, str(index), tuple(outline[0]), cv2.FONT_HERSHEY_SIMPLEX,
                                .6, (0, 0, 255), 2)
                writer.save_image(f"media/06_ocr/original_{key}.jpg", source)
                writer.save_image(f"media/06_ocr/overlay_{key}.png", overlay)
                row["texts"] = [box.text for box in boxes]
                calls.append(dict(call=call, frame=row["frame"], ts=row["ts"],
                                  text="\n".join(row["texts"]), boxes=len(boxes),
                                  score=sum(b.score for b in boxes) / len(boxes) if boxes else None,
                                  elapsed_s=elapsed, input_path=row["enhanced"]))
                writer.write_json("06_ocr/calls.json", calls)
                writer.write_json("06_ocr/boxes.json", all_boxes)
                writer.log(dict(event="ocr", **calls[-1]))
                writer.write_stage("06", status="running", metrics={"calls": call, "boxes": len(all_boxes)})
                print(f"[06] {call}/{len(records)} {row['ts']:.2f}s → {len(boxes)} 框 ({elapsed:.2f}s)", flush=True)
            writer.write_json("06_ocr/runtime.json", {"initialization_s": load_s,
                              "inference_s": sum(c["elapsed_s"] for c in calls)})
            writer.finish_stage("06", metrics={"calls": len(calls), "boxes": len(all_boxes),
                                "score": sum(scores) / len(scores) if scores else None})
            if not all_boxes:
                writer.warn("OCR 没有识别出文字；请检查区域标定、图像质量及模型设置。")

        with stage("08"):
            lines = ["# 逐帧 OCR 原文", "", "未跨帧去重，未校正识别错误；不代表最终课堂笔记。", ""]
            for row in records:
                lines.extend([f"## {row['ts']:.2f}s · frame {row['frame']}", ""])
                # 使用代码围栏，避免 OCR 原文被 Markdown 解释为标题或链接。
                text = "\n".join(row["texts"]) or "（未识别出文字）"
                fence = "`" * max(3, max((len(part) for part in re.findall(r'`+', text)), default=0) + 1)
                lines.extend([fence, text, fence, ""])
            notes = "\n".join(lines)
            writer.write_text("08_notes/notes.md", notes)
            writer.write_text("08_notes/notes.txt", "\n\n".join(
                f"[{row['ts']:.2f}s]\n" + "\n".join(row["texts"]) for row in records) + "\n")
            writer.set_outputs({"notes_md": "08_notes/notes.md", "notes_txt": "08_notes/notes.txt",
                                "ocr_boxes": "06_ocr/boxes.json"})
            writer.finish_stage("08", metrics={"sections": len(records),
                                "chars": sum(len(t) for row in records for t in row["texts"])},
                                note="逐帧原文；未去重或生成 PDF")

        with stage("09"):
            writer.write_json("09_stats/summary.json", timings)
            writer.finish_stage("09", metrics={"elapsed_s": time.perf_counter() - started,
                                "mem_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024},
                                note="进程累计峰值内存，Linux ru_maxrss；非教师行为统计")
        result = writer.finalize()
        if result["errors"]:
            raise RuntimeError(f"产物契约校验失败：{result['errors']}")
        return result
