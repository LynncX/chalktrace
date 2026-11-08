"""顺序编排最小流水线；不依赖 Web 或工作展示台。"""
from contextlib import contextmanager
from pathlib import Path
import resource
import time

import cv2
import numpy as np

from .adapters.ocr import OcrEngine
from .adapters.pose import PoseEngine
from .config import PipelineConfig
from .stages.s01_frames import blur_score, extract_frames
from .stages.s02_board import locate_board
from .stages.s03_pose import pose_overlay, project_people
from .stages.s04_gate import ChangeGate, gate_overlay
from .stages.s05_enhance import enhance_board
from .stages.s07_items import merge_items, bind_evidence
from .stages.s08_notes import write_notes


def read_image(path):
    image = cv2.imread(str(path))
    if image is None:
        raise RuntimeError(f"无法读取产物图像：{path}")
    return image


def run(video_path, config: PipelineConfig, writer, *, engine_factory=OcrEngine, pose_factory=PoseEngine):
    """writer 由调用方提供；engine_factory 便于无模型验证编排与坐标回溯。"""
    config.validate()
    video_path = Path(video_path)
    started = time.perf_counter()
    timings = []
    records = []
    gate_elapsed = 0.0

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
            seconds = time.perf_counter() - start - (gate_elapsed if no == "06" else 0)
            writer.finish_stage(no, duration_s=seconds)
            timings.append(dict(stage=no, seconds=seconds, frames=len(records),
                                note=writer.manifest.stage(no).note))
            print(f"[{no}] 完成 {seconds:.2f}s", flush=True)

    with writer:
        writer.write_config(config.to_dict())
        writer.warn("条目跟踪假定固定机位与固定标定；行拆分/合并、擦除重写和切镜头尚未专门处理，需核验识别历史。")
        if config.gate_mode == "fixed":
            writer.warn("固定采样基线：未执行人体遮挡估计与变化门控。")
        elif config.gate_mode == "change":
            writer.warn("仅变化门控：未屏蔽人体运动，变化可能来自教师而非板书。")
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

        if config.gate_mode == "occlusion_change":
            with stage("03"):
                pose_engine = pose_factory(config)
                pose_rows = []
                for row in records:
                    source = read_image(writer.root / row["path"])
                    people = pose_engine.detect(source)
                    mask, occlusion = project_people(people, row["calibration"])
                    row.update(occlusion=occlusion, mask_path=f"03_pose/masks/{row['frame']:08d}.png")
                    writer.save_image(row["mask_path"], mask)
                    path = f"media/03_pose/pose_{row['frame']:08d}.jpg"
                    writer.save_image(path, pose_overlay(source, people, occlusion))
                    pose_rows.append(dict(frame=row["frame"], ts=row["ts"], people=people, people_count=len(people),
                                          occlusion=occlusion, mask_path=row["mask_path"], path=path))
                    print(f"[03] {row['ts']:.2f}s 人体 {len(people)}，覆盖估计 {occlusion:.1%}", flush=True)
                writer.write_json("03_pose/poses.json", pose_rows)
                writer.finish_stage("03", metrics={"pose_frames": len(records),
                                    "occluded": sum(r["occlusion"] > config.occlusion_max for r in pose_rows)},
                                    note="YOLOv8n-pose ONNX；全部人体框投影并集/板书面积，不是 IoU 或精确分割")
                writer.warn("人体框覆盖率仅为保守遮挡估计；无人体检测结果不等于确认无遮挡。未估计教师身份、朝向或行为。")

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
            engine, load_s = None, 0.0
            calls, all_boxes, scores = [], [], []
            gate_rows = []
            gated = config.gate_mode != "fixed"
            gate = ChangeGate(config) if gated else None
            if gated:
                writer.begin_stage("04")
            for row in records:
                key = f"{row['frame']:08d}"
                board = read_image(writer.root / row["board"])
                mask = (cv2.imread(str(writer.root / row["mask_path"]), cv2.IMREAD_GRAYSCALE)
                        if "mask_path" in row else np.zeros(board.shape[:2], dtype="uint8"))
                if mask is None:
                    raise RuntimeError("无法读取遮挡掩码")
                if gated:
                    gate_start = time.perf_counter()
                    try:
                        info = gate.decide(board, mask, ts=row["ts"], occlusion=row.get("occlusion", 0.0))
                        info.update(frame=row["frame"], ts=row["ts"], clarity=blur_score(board))
                        audit_path = f"media/04_gate/decision_{key}.jpg"
                        writer.save_image(audit_path, gate_overlay(board, info))
                        info["audit_path"] = audit_path
                        gate_rows.append(info)
                        writer.write_json("04_gate/gate.json", gate_rows)
                        writer.log(dict(event="gate", **info))
                    except Exception as exc:
                        writer.fail_stage("04", str(exc))
                        raise
                    finally:
                        gate_elapsed += time.perf_counter() - gate_start
                    row["gate"] = info
                    if not info["fired"]:
                        print(f"[04] {row['ts']:.2f}s SKIP {info['reason']}", flush=True)
                        continue
                if engine is None:
                    load_start = time.perf_counter()
                    engine = engine_factory(config)
                    load_s = time.perf_counter() - load_start
                call = len(calls) + 1
                start = time.perf_counter()
                boxes = engine.recognize(read_image(writer.root / row["enhanced"]),
                                         frame=row["frame"], ts=row["ts"], call=call)
                elapsed = time.perf_counter() - start
                if gated:
                    gate.commit(board, mask, row["ts"])
                    writer.save_image(f"media/04_gate/fired_{key}.jpg", board)
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
            # 即使全部被遮挡拒绝，也输出空结果而不初始化 OCR 模型。
            writer.write_json("06_ocr/calls.json", calls)
            writer.write_json("06_ocr/boxes.json", all_boxes)
            if not all_boxes:
                writer.warn("OCR 没有识别出文字；请检查区域标定、图像质量及模型设置。")
            if gated:
                writer.finish_stage("04", metrics={"candidates": len(records), "passed": len(calls),
                                    "pass_rate": 100 * len(calls) / len(records),
                                    "skipped": len(records) - len(calls)}, duration_s=gate_elapsed,
                                    note="参考仅在 OCR 成功后更新；时间单位秒；人体遮挡优先于冷却与最长刷新间隔")
                timings.append(dict(stage="04", seconds=gate_elapsed, frames=len(records), note=config.gate_mode))

        with stage("07"):
            tracks = merge_items(all_boxes, calls)
            items = bind_evidence(tracks, writer)
            writer.finish_stage("07", metrics=dict(items=len(items), observations=len(all_boxes),
                                merged=sum(len(t["observations"])-1 for t in tracks)),
                                note="固定标定下行级位置+文本匹配；首末时间为实际观察；不推断擦除")

        with stage("08"):
            write_notes(items, calls, writer)

        with stage("09"):
            writer.write_json("09_stats/summary.json", timings)
            writer.finish_stage("09", metrics={"elapsed_s": time.perf_counter() - started,
                                "mem_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024},
                                note="进程累计峰值内存，Linux ru_maxrss；非教师行为统计")
        result = writer.finalize()
        if result["errors"]:
            raise RuntimeError(f"产物契约校验失败：{result['errors']}")
        return result
