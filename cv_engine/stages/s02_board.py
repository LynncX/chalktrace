"""显式人工标定；不把全帧直通宣称为自动定位。"""
import cv2
import numpy as np


def locate_board(image, config):
    height, width = image.shape[:2]
    if config.corners is not None:
        points = np.asarray(config.corners, dtype=np.float32)
        mode = "manual_corners"
    elif config.roi is not None:
        if len(config.roi) != 4 or any(type(v) is not int for v in config.roi):
            raise ValueError("roi 必须是四个整数 x,y,width,height")
        x, y, w, h = config.roi
        if w < 2 or h < 2:
            raise ValueError("ROI 宽高必须至少 2 像素")
        points = np.float32([[x, y], [x+w-1, y], [x+w-1, y+h-1], [x, y+h-1]])
        mode = "manual_roi"
    else:
        points = np.float32([[0, 0], [width-1, 0], [width-1, height-1], [0, height-1]])
        mode = "full_frame"
    if points.shape != (4, 2) or not np.isfinite(points).all():
        raise ValueError("corners 必须包含四个有限二维坐标")
    if (points < 0).any() or (points[:, 0] >= width).any() or (points[:, 1] >= height).any():
        raise ValueError("板书标定坐标超出图像范围")
    if not cv2.isContourConvex(points) or cv2.contourArea(points, oriented=True) <= 1:
        raise ValueError("四角必须按左上、右上、右下、左下排列成有效凸四边形")
    tl, tr, br, bl = points
    out_w = round(max(np.linalg.norm(tr-tl), np.linalg.norm(br-bl))) + 1
    out_h = round(max(np.linalg.norm(bl-tl), np.linalg.norm(br-tr))) + 1
    if min(out_w, out_h) < 2:
        raise ValueError("校正区域过小")
    target = np.float32([[0, 0], [out_w-1, 0], [out_w-1, out_h-1], [0, out_h-1]])
    matrix = cv2.getPerspectiveTransform(points, target)
    board = cv2.warpPerspective(image, matrix, (out_w, out_h))
    overlay = image.copy()
    cv2.polylines(overlay, [points.astype("int32")], True, (0, 200, 255), 2)
    return board, overlay, dict(mode=mode, corners=points.tolist(),
                               source_to_board=matrix.tolist(), output_size=[out_w, out_h])
