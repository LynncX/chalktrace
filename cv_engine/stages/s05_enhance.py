"""温和灰度 CLAHE；不放大、不二值化，坐标与校正板书保持一致。"""
import cv2


def enhance_board(image, method):
    if method == "none":
        return image.copy()
    if method != "clahe":
        raise ValueError(f"未知增强方法：{method}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
