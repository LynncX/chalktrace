"""任务准备、预测导入与带乐观锁的人工标注存储。"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
from datetime import datetime, timezone

import cv2
import numpy as np


class Conflict(ValueError):
    pass


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    tmp.replace(path)


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value):
        raise ValueError("ID 请使用 1–80 位英文字母、数字、下划线或短横线")
    return value


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def polygon(poly, width, height):
    if not isinstance(poly, list) or len(poly) < 3 or len(poly) > 200:
        raise ValueError("区域至少需要三个顶点，最多 200 个")
    for point in poly:
        if (not isinstance(point, list) or len(point) != 2 or
                not all(finite(v) for v in point) or
                not 0 <= point[0] <= width or not 0 <= point[1] <= height):
            raise ValueError("区域坐标必须在原图范围内")
    if abs(cv2.contourArea(np.array(poly, dtype=np.float32))) < 1:
        raise ValueError("区域面积太小")


def validate(dataset, annotation):
    if not isinstance(annotation, dict):
        raise ValueError("标注必须是对象")
    if annotation.get("dataset_id") != dataset["id"] or annotation.get("video_sha256") != dataset["video"]["sha256"]:
        raise ValueError("标注与视频指纹不匹配")
    if annotation.get("schema_version") != 1:
        raise ValueError("不支持的标注格式版本")
    tracks, scenes, frames = annotation.get("tracks"), annotation.get("scenes"), annotation.get("frames")
    if not all(isinstance(v, dict) for v in (tracks, scenes, frames)):
        raise ValueError("缺少场景、条目或帧标注")
    if set(frames) != {f["id"] for f in dataset["frames"]}:
        raise ValueError("帧集与任务不一致")
    w, h = dataset["video"]["width"], dataset["video"]["height"]
    for sid, scene in scenes.items():
        identifier(sid)
        polygon(scene["board"], w, h)
    for tid, track in tracks.items():
        identifier(tid)
        if track["scene_id"] not in scenes or not isinstance(track.get("versions"), dict):
            raise ValueError("条目场景或版本无效")
        for vid, text in track["versions"].items():
            identifier(vid)
            if not isinstance(text, str) or len(text) > 20000:
                raise ValueError("版本文字无效")
    ordering = {f["id"]: i for i, f in enumerate(dataset["frames"])}
    errors = []
    for fid, frame in frames.items():
        if frame["scene_id"] not in scenes or frame["status"] not in ("todo", "draft", "done"):
            raise ValueError("场景或完成状态无效")
        if frame.get("quality") not in ("clear", "blur", "uncertain") or frame.get("ocr_decision") not in ("recognize", "skip", "uncertain"):
            raise ValueError("帧级选项无效")
        reference = frame.get("reference_id")
        if reference is not None and (reference not in ordering or ordering[reference] >= ordering[fid]):
            raise ValueError("参考帧必须早于当前帧")
        events = frame.get("events", [])
        if not isinstance(events, list) or not set(events) <= {"unchanged", "added", "erased", "modified", "cut", "uncertain"}:
            raise ValueError("变化类型无效")
        if reference is None and events:
            raise ValueError("没有参考帧时不应标注帧对变化")
        if "unchanged" in events and len(events) > 1:
            raise ValueError("无变化不能与其他变化同时选择")
        for poly in frame.get("occluders", []):
            polygon(poly, w, h)
        seen = set()
        for obs in frame.get("observations", []):
            identifier(obs["id"])
            tid = obs["track_id"]
            if tid not in tracks or tracks[tid]["scene_id"] != frame["scene_id"] or tid in seen:
                raise ValueError("同一帧条目 ID 必须唯一且属于当前场景；分片应加入同一条目的多个区域")
            seen.add(tid)
            if obs["version_id"] not in tracks[tid]["versions"]:
                raise ValueError("条目内容版本不存在")
            if obs["visibility"] not in ("full", "partial", "hidden", "uncertain") or obs["change"] not in ("unchanged", "added", "erased", "rewritten", "uncertain"):
                raise ValueError("条目状态无效")
            if not isinstance(obs.get("visible_text"), str) or len(obs["visible_text"]) > 20000:
                raise ValueError("可见文字无效")
            for poly in obs["regions"]:
                polygon(poly, w, h)
            if obs["visibility"] == "hidden" and (obs["regions"] or obs["visible_text"]):
                errors.append(f"{fid}/{tid}：完全遮挡时须清空可见区域及文字")
            if obs["visibility"] != "hidden" and not obs["regions"]:
                errors.append(f"{fid}/{tid}：缺少可见区域")
            if not obs.get("confirmed"):
                errors.append(f"{fid}/{tid}：条目尚未确认")
        if frame["status"] == "done":
            problems = [e for e in errors if e.startswith(fid + "/")]
            if not frame.get("reviewed") or (reference and not events):
                problems.append(f"{fid}：请确认帧级核验与参考帧变化")
            if problems:
                raise ValueError("；".join(problems))
    return errors


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self.engine = None

    def resolve(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("路径必须位于项目目录内")
        return path

    def paths(self, task):
        task = identifier(task)
        return (self.root / "evaluation/datasets" / task / "manifest.json",
                self.root / "evaluation/annotations" / task / "annotations.json",
                self.root / ".cache/annotation" / task)

    def tasks(self):
        result = []
        for path in sorted((self.root / "evaluation/datasets").glob("*/manifest.json")):
            data = read(path)
            ann = read(self.paths(data["id"])[1])
            result.append({"id": data["id"], "title": data["title"], "frames": len(data["frames"]),
                           "done": sum(f["status"] == "done" for f in ann["frames"].values())})
        return result

    def load(self, task):
        manifest, annotations, cache = self.paths(task)
        dataset, ann = read(manifest), read(annotations)
        predictions = read(cache / "predictions.json") if (cache / "predictions.json").exists() else {}
        return {"dataset": dataset, "annotation": ann, "predictions": predictions,
                "issues": validate(dataset, ann)}

    def create(self, spec):
        with self.lock:
            task = identifier(spec["id"])
            manifest, annotations, cache = self.paths(task)
            if manifest.exists() or annotations.exists():
                raise ValueError("任务 ID 已存在")
            video = self.resolve(spec["video"])
            if not video.is_file():
                raise ValueError("找不到视频")
            cap = cv2.VideoCapture(str(video))
            try:
                fps, total = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                if fps <= 0 or total <= 0 or width <= 0:
                    raise ValueError("视频无法读取")
                segments = spec["segments"]
                if not isinstance(segments, list) or not 1 <= len(segments) <= 20:
                    raise ValueError("请提供 1–20 个片段")
                selected = {}
                scenes = {}
                for index, segment in enumerate(segments):
                    start, end, step = segment["start"], segment["end"], segment["interval"]
                    if not all(finite(x) for x in (start, end, step)) or not 0 <= start < end <= total / fps or step <= 0:
                        raise ValueError("片段起止时间或间隔无效（结束时间不超过视频时长）")
                    if (end - start) / step > 500:
                        raise ValueError("每个片段最多 500 帧")
                    sid = f"S{index + 1:02d}"
                    scenes[sid] = {"name": segment.get("name", sid), "board": [[0, 0], [width, 0], [width, height], [0, height]]}
                    for n in range(math.ceil((end - start) / step)):
                        requested = start + n * step
                        if requested >= end:
                            break
                        number = min(total - 1, int(round(requested * fps)))
                        if number in selected:
                            raise ValueError("片段包含重复采样帧，请调整边界")
                        selected[number] = (sid, "regular", requested)
                for extra in spec.get("extras", []):
                    ts, sid = extra["time"], extra["scene_id"]
                    if not finite(ts) or not 0 <= ts < total / fps or sid not in scenes:
                        raise ValueError("补充帧时间或场景无效")
                    selected.setdefault(min(total - 1, int(round(ts * fps))), (sid, "supplement", ts))
                if len(selected) > 1000:
                    raise ValueError("单任务最多 1000 帧")
                with video.open("rb") as stream:
                    digest = hashlib.file_digest(stream, "sha256").hexdigest()
                frames, frame_ann = [], {}
                previous = {}
                cache.mkdir(parents=True, exist_ok=True)
                for number, (sid, origin, requested) in sorted(selected.items()):
                    fid = f"F{number:08d}"
                    cap.set(cv2.CAP_PROP_POS_FRAMES, number)
                    ok, image = cap.read()
                    if not ok:
                        raise ValueError(f"解码失败：{number}")
                    if not cv2.imwrite(str(cache / f"{fid}.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                        raise ValueError("图片写入失败")
                    frames.append({"id": fid, "number": number, "time": number / fps, "requested_time": requested, "origin": origin, "scene_id": sid})
                    frame_ann[fid] = {"scene_id": sid, "reference_id": previous.get(sid), "status": "todo", "quality": "clear",
                                      "ocr_decision": "uncertain", "events": [], "reviewed": False,
                                      "occluders": [], "observations": [], "note": ""}
                    previous[sid] = fid
                dataset = {"schema_version": 1, "id": task, "title": spec.get("title") or task,
                           "created_at": datetime.now(timezone.utc).isoformat(), "segments": segments,
                           "sampling": "fixed_before_quality_filter", "video": {"path": str(video.relative_to(self.root)),
                           "sha256": digest, "fps": fps, "frames": total, "width": width, "height": height}, "frames": frames}
                ann = {"schema_version": 1, "dataset_id": task, "video_sha256": digest,
                       "revision": 0, "scenes": scenes, "tracks": {}, "frames": frame_ann}
                atomic(annotations, ann)
                atomic(manifest, dataset)
                atomic(cache / "predictions.json", {})
                return self.load(task)
            finally:
                cap.release()

    def save(self, task, annotation):
        with self.lock:
            manifest, path, _ = self.paths(task)
            current = read(path)
            if annotation.get("revision") != current["revision"]:
                raise Conflict("其他窗口已修改此任务。请导出本页草稿，再重新载入，避免覆盖")
            issues = validate(read(manifest), annotation)
            annotation["revision"] += 1
            annotation["saved_at"] = datetime.now(timezone.utc).isoformat()
            atomic(path.with_suffix(".previous.json"), current)
            atomic(path, annotation)
            return {"revision": annotation["revision"], "saved_at": annotation["saved_at"], "issues": issues}

    def import_run(self, task, run):
        with self.lock:
            data = self.load(task)
            dataset = data["dataset"]
            run_path = self.resolve(run)
            if not run_path.is_dir():
                raise ValueError("请输入运行目录，例如 runs/items_trial_v1")
            manifest = read(run_path / "manifest.json")
            video = dataset["video"]
            info = manifest["video"]
            if (info.get("name") != Path(video["path"]).name or
                    any(info.get(k) != video[k] for k in ("width", "height", "frames")) or
                    abs(info.get("fps", 0) - video["fps"]) > .001):
                raise ValueError("运行视频信息与任务不匹配")
            by_number = {f["number"]: f for f in dataset["frames"]}
            predictions = data["predictions"]
            imported = 0
            cache = self.paths(task)[2]
            grouped = {}
            for box in read(run_path / "06_ocr/boxes.json"):
                if box["frame"] in by_number:
                    grouped.setdefault(box["frame"], []).append(box)
            for number, boxes in grouped.items():
                fid = by_number[number]["id"]
                source = (run_path / boxes[0]["source_path"]).resolve()
                if not source.is_relative_to(run_path):
                    raise ValueError("运行图片路径无效")
                original = cv2.imread(str(source))
                target = cv2.imread(str(cache / f"{fid}.jpg"))
                # 旧 run 没有视频指纹，必须额外核验同一原始帧的像素；容许 JPEG 重编码误差。
                if original is None or target is None or original.shape != target.shape or np.abs(original.astype(float) - target).mean() > 4:
                    raise ValueError(f"{fid} 原帧不匹配，拒绝导入")
                rows = []
                for i, box in enumerate(boxes):
                    poly = box.get("source_poly")
                    if poly is None:
                        raise ValueError("运行缺少原图坐标 source_poly，不能直接导入白板坐标")
                    poly = [[max(0, min(video["width"], float(x))), max(0, min(video["height"], float(y)))] for x, y in poly]
                    polygon(poly, video["width"], video["height"])
                    rows.append({"id": f"run-{i}", "text": box["text"], "regions": [poly], "score": box["score"],
                                 "source": str(run_path.relative_to(self.root)), "frame": number})
                predictions[fid] = rows
                imported += len(rows)
            atomic(cache / "predictions.json", predictions)
            return {"imported": imported, "frames": len(grouped), "data": self.load(task)}

    def ocr(self, task, fid):
        with self.lock:
            data = self.load(task)
            frames = {f["id"]: f for f in data["dataset"]["frames"]}
            if fid not in frames:
                raise ValueError("帧不存在")
            from cv_engine.adapters.ocr import OcrEngine
            from cv_engine.config import PipelineConfig
            if self.engine is None:
                self.engine = OcrEngine(PipelineConfig())
            image = cv2.imread(str(self.paths(task)[2] / f"{fid}.jpg"))
            f = frames[fid]
            boxes = self.engine.recognize(image, frame=f["number"], ts=f["time"], call=1)
            predictions = data["predictions"]
            predictions[fid] = [{"id": f"ocr-{i}", "text": b.text, "regions": [b.poly], "score": b.score,
                                 "source": "PP-OCRv5/original-frame", "frame": f["number"]} for i, b in enumerate(boxes)]
            atomic(self.paths(task)[2] / "predictions.json", predictions)
            return self.load(task)

    def regenerate(self, task):
        """缓存可删除：按固定帧清单恢复图片，核验视频 SHA256，保留人工标注。"""
        with self.lock:
            manifest, _, cache = self.paths(task)
            dataset = read(manifest)
            video = self.resolve(dataset["video"]["path"])
            with video.open("rb") as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != dataset["video"]["sha256"]:
                    raise ValueError("视频指纹已变化，不能重建")
            cap = cv2.VideoCapture(str(video))
            try:
                cache.mkdir(parents=True, exist_ok=True)
                for f in dataset["frames"]:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, f["number"])
                    ok, image = cap.read()
                    if not ok or not cv2.imwrite(str(cache / f'{f["id"]}.jpg'), image, [cv2.IMWRITE_JPEG_QUALITY, 95]):
                        raise ValueError("重建图片失败")
            finally:
                cap.release()
            return self.load(task)
