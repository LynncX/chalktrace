"""YOLOv8n-pose ONNX + OpenCV DNN CPU；无 PyTorch 依赖。

ONNX 由 unileon-robotics 导出；固定仓库 revision 和 LFS SHA256。
原模型与格式说明：https://docs.ultralytics.com/tasks/pose/
"""
from pathlib import Path
import hashlib
import os
import urllib.request

import cv2
import numpy as np

MODEL_URL = "https://huggingface.co/unileon-robotics/YOLO8-ONNX/resolve/66e5888954d3454da709847e77b36df31f756aa9/yolov8n-pose.onnx"
MODEL_SHA256 = "6fc546ff26e38b25e29c047fcacd71d3607705c0b5a590f0bd97492aed459f94"


def ensure_model():
    root = Path(__file__).resolve().parents[2]
    path = root / ".cache" / "pose" / "yolov8n-pose.onnx"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        print("[03] 下载 YOLOv8n-pose ONNX（约 13 MB）", flush=True)
        temp = path.with_suffix(".download")
        try:
            with urllib.request.urlopen(MODEL_URL, timeout=60) as response, temp.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if hashlib.sha256(temp.read_bytes()).hexdigest() != MODEL_SHA256:
                raise RuntimeError("姿态模型 SHA256 校验失败")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    if hashlib.sha256(path.read_bytes()).hexdigest() != MODEL_SHA256:
        raise RuntimeError(f"姿态模型缓存损坏，请删除后重试：{path}")
    return path


class PoseEngine:
    def __init__(self, config):
        self.conf = config.pose_conf
        self.net = cv2.dnn.readNetFromONNX(str(ensure_model()))
        self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)

    def detect(self, image):
        height, width = image.shape[:2]
        # 固定哈希的导出模型输入为 NCHW [1,3,480,640]，不是常见的 640×640。
        scale = min(640 / width, 480 / height)
        resized = cv2.resize(image, (round(width * scale), round(height * scale)))
        left = (640 - resized.shape[1]) // 2
        top = (480 - resized.shape[0]) // 2
        canvas = np.full((480, 640, 3), 114, dtype="uint8")
        canvas[top:top+resized.shape[0], left:left+resized.shape[1]] = resized
        self.net.setInput(cv2.dnn.blobFromImage(canvas, 1 / 255, (640, 480), swapRB=True))
        output = self.net.forward()
        if output.ndim != 3 or output.shape[0] != 1 or output.shape[1] != 56:
            raise RuntimeError(f"不支持的 pose ONNX 输出形状：{output.shape}")
        candidates = output[0].T
        candidates = candidates[candidates[:, 4] >= self.conf]
        rects, scores = [], []
        for row in candidates:
            cx, cy, w, h = row[:4]
            rects.append([float(cx-w/2), float(cy-h/2), float(w), float(h)])
            scores.append(float(row[4]))
        keep = cv2.dnn.NMSBoxes(rects, scores, self.conf, .45)
        people = []
        for index in np.asarray(keep).reshape(-1):
            row = candidates[int(index)]
            cx, cy, w, h = row[:4]
            xyxy = np.array([cx-w/2, cy-h/2, cx+w/2, cy+h/2], dtype="float32")
            xyxy[[0, 2]] = np.clip((xyxy[[0, 2]]-left) / scale, 0, width-1)
            xyxy[[1, 3]] = np.clip((xyxy[[1, 3]]-top) / scale, 0, height-1)
            kpts = row[5:].reshape(17, 3).copy()
            kpts[:, 0] = (kpts[:, 0]-left) / scale
            kpts[:, 1] = (kpts[:, 1]-top) / scale
            people.append(dict(bbox=xyxy.tolist(), score=float(row[4]), keypoints=kpts.tolist()))
        return people
