"""基于上一次实际 OCR 参考图的可见区域变化门控。"""
import cv2
import numpy as np

REASONS = {"occluded": "人体覆盖超阈值", "cooldown": "冷却期", "first_visible": "首个可用帧",
           "visibility_recovery": "新区域显露", "insufficient_overlap": "共同可见区域不足，保守放行",
           "changed": "可见区域变化", "unchanged": "可见区域无明显变化", "max_gap": "达到最长刷新间隔"}


def comparison_image(image, mask):
    height, width = image.shape[:2]
    scale = min(1, 640 / max(height, width))
    size = (max(12, round(width * scale)), max(12, round(height * scale)))
    gray = cv2.resize(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), size, interpolation=cv2.INTER_AREA)
    hidden = cv2.resize(mask, size, interpolation=cv2.INTER_NEAREST) > 0
    return gray, hidden


def masked_change(current, reference, visible, diff_threshold):
    """11×11 Gaussian SSIM，仅统计窗口内均可见的像素。"""
    valid = cv2.erode(visible.astype("uint8"), np.ones((11, 11), dtype="uint8")) > 0
    if not valid.any():
        return None, None
    a, b = current.astype("float32"), reference.astype("float32")
    blur = lambda image: cv2.GaussianBlur(image, (11, 11), 1.5)
    ma, mb = blur(a), blur(b)
    va, vb = np.maximum(0, blur(a*a)-ma*ma), np.maximum(0, blur(b*b)-mb*mb)
    covariance = blur(a*b)-ma*mb
    c1, c2 = (0.01*255)**2, (0.03*255)**2
    similarity = ((2*ma*mb+c1)*(2*covariance+c2)) / ((ma*ma+mb*mb+c1)*(va+vb+c2))
    ratio = float(np.mean(np.abs(a[valid]-b[valid]) >= diff_threshold))
    return float(np.clip(similarity[valid].mean(), -1, 1)), ratio


class ChangeGate:
    def __init__(self, config):
        self.config = config
        self.reference = None
        self.reference_hidden = None
        self.reference_ts = None

    def decide(self, image, mask, *, ts, occlusion):
        gray, hidden = comparison_image(image, mask)
        c = self.config
        info = dict(ssim=None, change_ratio=None, visible_gain=None, common_visible=None,
                    reference_ts=self.reference_ts, occlusion=occlusion)
        reason, fired = "unchanged", False
        if c.gate_mode == "occlusion_change" and occlusion > c.occlusion_max:
            reason = "occluded"
        elif self.reference is None:
            reason, fired = "first_visible", True
        elif ts - self.reference_ts < c.cooldown_s:
            reason = "cooldown"
        else:
            visible = ~(hidden | self.reference_hidden)
            info["common_visible"] = float(visible.mean())
            info["visible_gain"] = float((self.reference_hidden & ~hidden).mean())
            info["ssim"], info["change_ratio"] = masked_change(gray, self.reference, visible, c.diff_threshold)
            if info["visible_gain"] >= c.visibility_gain_min:
                reason, fired = "visibility_recovery", True
            elif info["common_visible"] < c.common_visible_min or info["ssim"] is None:
                reason, fired = "insufficient_overlap", True
            elif info["ssim"] < c.ssim_min and info["change_ratio"] >= c.change_ratio_min:
                reason, fired = "changed", True
            elif ts - self.reference_ts >= c.max_gap_s:
                reason, fired = "max_gap", True
        info.update(reason=reason, reason_text=REASONS[reason], fired=fired)
        return info

    def commit(self, image, mask, ts):
        """只在 OCR 成功后调用；被跳过或推理失败的帧不更新参考。"""
        self.reference, self.reference_hidden = comparison_image(image, mask)
        self.reference_ts = ts


def gate_overlay(image, info):
    output = image.copy()
    color = (60, 190, 60) if info["fired"] else (60, 80, 240)
    lines = [f"{'OCR' if info['fired'] else 'SKIP'}: {info['reason']}  t={info['ts']:.2f}s",
             f"bbox/board={info['occlusion']:.1%}  SSIM={info['ssim']}  change={info['change_ratio']}"]
    cv2.rectangle(output, (0, 0), (image.shape[1], 76), (20, 20, 20), -1)
    for index, text in enumerate(lines):
        cv2.putText(output, text, (10, 26 + index * 32), cv2.FONT_HERSHEY_SIMPLEX, .6, color, 2)
    return output
