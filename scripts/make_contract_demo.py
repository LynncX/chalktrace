"""C / D 照抄这个：用 writer.py 产出一份形状真实、可被工作台直接渲染的 run。

    python scripts/make_contract_demo.py
    python -m workbench.build --run contract_demo

图片是合成示例，仅演示「写哪里 / 怎么调 writer」；真实产物请换成 CV 结果。
刻意不写 media/03_pose/pose_demo.mp4，用来验证「缺失显示占位、不补图」。
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from make_demo_run import board, chart                      # 复用示例绘图，避免重复造轮子
from cv_engine import BoardItem, OcrBox, RunWriter, StageStatus

METRICS = {
    "01": {"sampled": 2236, "blur_dropped": 0},
    "02": {"located": 2236, "confidence": 0.93},
    "03": {"pose_frames": 2236, "occluded": 418},
    "04": {"passed": 17, "pass_rate": 0.8},
    "05": {"snapshots": 17, "clarity": 0.71},
    "06": {"calls": 17, "boxes": 143, "score": 0.89},
    "08": {"sections": 6, "chars": 1284},
    "09": {"elapsed_s": 742.5, "mem_mb": 1860},
}
GLOBS = {
    "01_frames": [("sample_{:04d}.jpg", "JPEG", 3)],
    "02_board": [("calib_{:02d}.png", "PNG", 2), ("bbox_{:02d}.png", "PNG", 2)],
    "03_pose": [("pose_{:02d}.jpg", "JPEG", 3), ("occlusion_{:02d}.png", "PNG", 2)],
    "04_gate": [("fired_{:02d}.jpg", "JPEG", 3)],
    "05_enhance": [("f_{:02d}_color.jpg", "JPEG", 3), ("enhanced_{:02d}.png", "PNG", 3)],
    "06_ocr": [("original_{:02d}.jpg", "JPEG", 3), ("overlay_{:02d}.png", "PNG", 3)],
    "07_items": [("box_{:02d}.png", "PNG", 3), ("lifecycle_{:02d}.png", "PNG", 2)],
    "09_stats": [("timeline_{:02d}.png", "PNG", 2)],
}


def enc(img, fmt: str) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=78)
    return buf.getvalue()


def main() -> None:
    with RunWriter(
        "contract_demo",
        title="契约闭环演示 · writer 真实产物",
        video={"name": "clip01.mp4", "frames": 33528, "fps": 30,
               "duration_s": 1117.62, "width": 2560, "height": 1440},
        config={"SSIM_MAX": 0.88, "COOLDOWN_FRAMES": 30, "FRAME_SKIP": 15},
    ) as w:
        for no, name in [("01", "01_frames"), ("02", "02_board"), ("03", "03_pose"),
                         ("04", "04_gate"), ("05", "05_enhance"), ("06", "06_ocr"),
                         ("07", "07_items"), ("08", "08_notes"), ("09", "09_stats")]:
            w.begin_stage(no)
            for pattern, fmt, count in GLOBS.get(name, []):
                for i in range(count):
                    img = chart(560, 320, i + int(no)) if fmt == "PNG" else board(560, 320, i + int(no))
                    w.save_image(f"media/{name}/{pattern.format(i + 1)}", enc(img, fmt))
            if no in ("01", "04", "06", "09"):
                w.write_json(f"{name}/{ {'01':'frames','04':'gate','06':'calls','09':'summary'}[no]}.json",
                             [{"frame": i * 15, "ts": i * 0.5, "note": f"第 {i} 条"}
                              for i in range(1, 4)])
            if no == "08":
                w.write_text("08_notes/notes.md", "# 课堂笔记\n\n[Board Section 1] 卷积与池化。\n")
            w.finish_stage(no, metrics=METRICS.get(no), duration_s=round(1.5 + int(no) * 0.4, 1))

        for i in range(1, 4):
            w.write_item(BoardItem(
                item_id=f"IT-{i:03d}", text=["卷积与池化", "反向传播与链式法则", "梯度下降与学习率"][i - 1],
                first_seen_sec=120.5 * i, last_seen_sec=305.0 * i,
                frame=f"media/07_items/box_{i:02d}.png",
                crop=f"media/07_items/lifecycle_{i:02d}.png",
                ocr_link="#06", status=StageStatus.DONE.value,
                bbox=[212, 148, 96, 34], evidence={"overlay": f"media/07_items/box_{i:02d}.png"},
                best=OcrBox(text="货币政策", poly=[[212, 148], [308, 148], [308, 182], [212, 182]],
                            score=0.93, frame=1269 * i, ts=42.3, ocr_call=i),
            ))

        w.set_outputs({"notes_txt": "08_notes/notes.md"})
        w.set_compare([
            {"配置": "A 原始链路", "门控策略": "固定间隔", "OCR 调用": 2236, "条目数": 61, "人工核对": "未做"},
            {"配置": "C 分区门控", "门控策略": "SSIM + 遮挡", "OCR 调用": 17, "条目数": 12, "人工核对": "全量"},
        ])
        result = w.finalize()

    print(f"manifest: {result['path']}")
    print(f"产物 {result['files']} 个 | 契约校验 {len(result['errors'])} 条错误")
    for err in result["errors"]:
        print("  !", err)
    print("下一步：python -m workbench.build --run contract_demo")


if __name__ == "__main__":
    main()
