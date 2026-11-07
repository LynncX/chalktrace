"""生成 experiments/demo_experiment/ 的示例实验（manifest + 逐变体结果图）。

仅用于工作台联调；真实实验由各成员单独跑某个 stage 后落盘。
刻意不写 psm6 的样本 21 图，用来验证「缺失单元格显示占位」。

用法：python scripts/make_demo_experiment.py
"""
from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "workbench" / "fixtures" / "demo_experiment"
DST = ROOT / "experiments" / "demo_experiment"

# (variant_id, 检测框数, 框颜色, 框随机种子)；底图只由样本 id 决定，保证输入一致
PLAN = [
    ("baseline", 12, (150, 156, 166), 11),
    ("clahe_on", 14, (47, 111, 235), 22),
    ("psm6",     10, (186, 117, 23), 33),
]
SKIP = {("psm6", "21")}


def result_frame(sample_id: int, boxes: int, color: tuple[int, int, int],
                 seed: int) -> Image.Image:
    w, h = 720, 450
    rng = random.Random(sample_id)          # 同一输入 → 底图完全一致
    img = Image.new("RGB", (w, h), (248, 249, 246))
    d = ImageDraw.Draw(img)
    for y in range(60, h, 34):
        d.line([(40, y), (w - 40, y)], fill=(232, 234, 230), width=1)
    ink = (38, 45, 58)
    for r in range(5):
        y = 78 + r * 68
        end = int(w * rng.uniform(0.35, 0.85))
        pts = [(x, y + rng.randint(-3, 3)) for x in range(48, end, 12)]
        if len(pts) > 1:
            d.line(pts, fill=ink, width=2)
    brng = random.Random(seed)
    for _ in range(boxes):
        x1 = brng.randint(30, w - 170)
        y1 = brng.randint(40, h - 70)
        x2 = min(w - 12, x1 + brng.randint(90, 220))
        y2 = min(h - 12, y1 + brng.randint(18, 40))
        d.rectangle([x1, y1, x2, y2], outline=color, width=2)
    return img


def main() -> None:
    DST.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC / "manifest.json", DST / "manifest.json")
    mf = json.loads((DST / "manifest.json").read_text(encoding="utf-8"))
    meta = {p[0]: p for p in PLAN}
    sizes: dict[str, int] = {}
    for v in mf["variants"]:
        _, boxes, color, seed = meta[v["id"]]
        for sid, rel in (v.get("images") or {}).items():
            if (v["id"], sid) in SKIP:
                continue
            p = DST / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            result_frame(int(sid), boxes, color, seed).save(p, "PNG")
            sizes[rel] = p.stat().st_size
    print(f"示例实验已生成：{DST}")
    for rel, size in sorted(sizes.items()):
        print(f"  {size / 1024:>8.1f} KB  {rel}")
    for vid, sid in sorted(SKIP):
        print(f"  刻意缺失   media/{vid}/s{sid}.png")


if __name__ == "__main__":
    main()
