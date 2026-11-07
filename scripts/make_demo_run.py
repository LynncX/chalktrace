"""生成 runs/demo_mock/ 的示例产物（媒体 + 数据表）。

仅用于工作台联调与答辩演示；真实产物由 cv_engine 逐阶段写入 runs/<run_id>/。
刻意不生成 media/03_pose/pose_demo.mp4，用来验证「缺失产物显示占位」。

用法：python scripts/make_demo_run.py
"""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "workbench" / "fixtures" / "demo_mock"
DST = ROOT / "runs" / "demo_mock"


def board(w: int, h: int, seed: int, rows: int = 6) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), (248, 249, 246))
    d = ImageDraw.Draw(img)
    step = max(26, h // 16)
    for y in range(int(h * 0.18), h, step):
        d.line([(int(w * 0.06), y), (int(w * 0.94), y)], fill=(232, 234, 230), width=1)
    d.rectangle([int(w * 0.06), int(h * 0.08), int(w * 0.42),
                 int(h * 0.08) + max(6, h // 55)], fill=(47, 111, 235))
    ink = (38, 45, 58)
    for r in range(rows):
        y = int(h * 0.22) + r * step * 2
        x = int(w * 0.07)
        end = min(int(w * 0.92), x + int(w * rng.uniform(0.35, 0.82)))
        pts = []
        while x < end:
            pts.append((x, y + rng.randint(-4, 4)))
            x += rng.randint(8, 18)
        if len(pts) > 1:
            d.line(pts, fill=ink, width=max(2, w // 450))
    return img


def chart(w: int, h: int, seed: int) -> Image.Image:
    rng = random.Random(seed)
    img = Image.new("RGB", (w, h), (250, 251, 252))
    d = ImageDraw.Draw(img)
    m = int(w * 0.08)
    d.line([(m, h - m), (w - m, h - m)], fill=(200, 205, 212), width=2)
    d.line([(m, m), (m, h - m)], fill=(200, 205, 212), width=2)
    for color, base in [((47, 111, 235), 0.55), ((29, 158, 117), 0.35)]:
        pts = [(m + int((w - 2 * m) * i / 59),
                m + int((h - 2 * m) * (base + 0.18 * rng.random())))
               for i in range(60)]
        d.line(pts, fill=color, width=3)
    y = m + int((h - 2 * m) * 0.30)
    d.line([(m, y), (w - m, y)], fill=(226, 75, 74), width=1)
    return img


def put(rel: str, img: Image.Image, fmt: str = "JPEG",
        quality: int = 80, noise: float = 0.0) -> int:
    p = DST / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    im = img
    if noise > 0:                        # 噪声降低压缩率，用来造出中 / 大档素材
        n = Image.effect_noise(img.size, 24).convert("RGB")
        im = Image.blend(img, n, noise)
    if fmt == "PNG":
        im.save(p, "PNG")
    else:
        im.convert("RGB").save(p, "JPEG", quality=quality, optimize=True)
    return p.stat().st_size


def write_json(rel: str, rows: list[dict]) -> None:
    p = DST / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC / "manifest.json", DST / "manifest.json")

    sizes: dict[str, int] = {}
    sizes["media/01_frames/sample_0000.jpg"] = put(
        "media/01_frames/sample_0000.jpg", board(640, 420, 1, 4), "JPEG", 72)
    sizes["media/01_frames/contact_sheet.jpg"] = put(
        "media/01_frames/contact_sheet.jpg", board(1400, 800, 2, 8), "JPEG", 92, 0.18)
    sizes["media/02_board/roi.png"] = put(
        "media/02_board/roi.png", board(760, 480, 3, 5), "PNG")
    sizes["media/03_pose/pose_overlay.jpg"] = put(
        "media/03_pose/pose_overlay.jpg", board(1280, 720, 4, 6), "JPEG", 92, 0.15)
    sizes["media/04_gate/ssim_chart.png"] = put(
        "media/04_gate/ssim_chart.png", chart(1000, 520, 5), "PNG")
    sizes["media/05_enhance/board_017.png"] = put(
        "media/05_enhance/board_017.png", board(1000, 620, 6, 7), "PNG", noise=0.22)
    sizes["media/05_enhance/board_full.png"] = put(
        "media/05_enhance/board_full.png", board(1800, 1100, 7, 10), "PNG", noise=0.45)
    sizes["media/06_ocr/overlay_017.png"] = put(
        "media/06_ocr/overlay_017.png", board(1000, 620, 8, 7), "PNG", noise=0.18)
    sizes["media/09_stats/timeline.png"] = put(
        "media/09_stats/timeline.png", chart(900, 380, 9), "PNG")
    sizes["media/poster.jpg"] = put(
        "media/poster.jpg", board(960, 540, 10, 5), "JPEG", 78)
    for i in range(1, 5):
        sizes[f"media/07_items/frame_00{i}.jpg"] = put(
            f"media/07_items/frame_00{i}.jpg", board(720, 450, 20 + i, 4), "JPEG", 74)
        sizes[f"media/07_items/crop_00{i}.png"] = put(
            f"media/07_items/crop_00{i}.png", board(420, 240, 30 + i, 2), "PNG")

    write_json("01_frames/frames.json", [
        {"frame": i * 15, "ts": round(i * 0.5, 1), "blur": round(60 + i * 3.7, 1),
         "kept": "是" if i % 4 else "否"} for i in range(8)
    ])
    write_json("04_gate/gate.json", [
        {"frame": 150 + i * 900, "ts": round(5 + i * 30, 1),
         "ssim": round(0.72 + i * 0.02, 3), "clarity": round(0.5 + i * 0.04, 2),
         "fired": "是" if i % 3 == 0 else "否"} for i in range(8)
    ])
    write_json("06_ocr/calls.json", [
        {"call": f"C-{i:03d}", "frame": 150 + i * 900, "ts": round(5 + i * 30, 1),
         "text": t, "score": round(0.82 + i * 0.02, 2)}
        for i, t in enumerate(["卷积与池化", "反向传播", "梯度下降", "过拟合",
                               "正则化", "学习率"])
    ])
    write_json("09_stats/summary.json", [
        {"stage": f"0{i}", "seconds": round(60 + i * 42.5, 1), "frames": 33528 // (i + 1),
         "note": n} for i, n in enumerate(["解码", "定位", "姿态", "门控", "增强", "识别"], 1)
    ])
    (DST / "08_notes").mkdir(parents=True, exist_ok=True)
    (DST / "08_notes" / "notes.md").write_text(
        "# 课堂笔记（示例）\n\n"
        "[Board Section 1] 卷积与池化：局部感受野、权值共享、下采样。\n\n"
        "[Board Section 2] 反向传播与链式法则：误差逐层回传。\n\n"
        "[Board Section 3] 梯度下降与学习率：步长过大易震荡。\n\n"
        "[Board Section 4] 过拟合与正则化：L2 与 dropout。\n",
        encoding="utf-8")

    print(f"示例 run 已生成：{DST}")
    for rel, size in sorted(sizes.items()):
        tier = "①内联" if size < 100 * 1024 else ("②缩略图" if size <= 2 * 1024 * 1024 else "③引用")
        print(f"  {tier:<8} {size / 1024:>8.1f} KB  {rel}")
    print("  刻意缺失   media/03_pose/pose_demo.mp4")


if __name__ == "__main__":
    main()
