"""按视频帧号采样，保留真实时间戳与质量分数。"""
import cv2
import numpy as np


def blur_score(image):
    return float(cv2.Laplacian(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())


def extract_frames(video_path, config, writer):
    cap = cv2.VideoCapture(str(video_path))
    try:
        if not cap.isOpened():
            raise ValueError(f"无法打开视频：{video_path}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if not np.isfinite(fps) or fps <= 0 or count <= 0:
            raise ValueError("视频缺少有效 FPS 或帧数")
        duration = count / fps
        if config.start_s >= duration:
            raise ValueError("采样起点超出视频时长")
        end = min(duration, config.end_s if config.end_s is not None else duration)
        writer.set_video(name=video_path.name, fps=fps, frames=count, duration_s=duration,
                         width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        rows, kept, thumbs = [], [], []
        previous = -1
        for index in range(config.max_frames):
            ts = config.start_s + index * config.sample_interval_s
            if ts >= end:
                break
            target = round(ts * fps)
            if target >= count:
                break
            if target == previous:
                raise ValueError("采样间隔小于一帧，请增大 sample_interval_s")
            previous = target
            cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            ok, image = cap.read()
            if not ok:
                raise RuntimeError(f"视频帧 {target} 解码失败")
            actual = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
            if actual / fps >= end:
                break
            path = f"media/01_frames/sample_{actual:08d}.jpg"
            writer.save_image(path, image)
            score = blur_score(image)
            row = dict(frame=actual, ts=actual / fps, blur=score,
                       kept=score >= config.blur_min, path=path)
            rows.append(row)
            writer.write_json("01_frames/frames.json", rows)
            if len(thumbs) < 24:
                thumb = cv2.resize(image, (320, max(1, round(image.shape[0] * 320 / image.shape[1]))))
                cv2.putText(thumb, f"{actual / fps:.2f}s", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 255), 2)
                thumbs.append(thumb)
            if row["kept"]:
                kept.append(row)
        if thumbs:
            writer.save_image("media/01_frames/contact_sheet.jpg", np.concatenate(thumbs, axis=0))
        if not kept:
            raise ValueError("无可用采样帧：请检查采样区间或降低 blur_min")
        return rows, kept
    finally:
        cap.release()
