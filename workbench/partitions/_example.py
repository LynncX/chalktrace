"""复杂 tab 的逃生口写法（示例文件，下划线开头，registry 会自动跳过）。

当某个 tab 需要循环 / 条件 / 跨 tab 跳转，YAML 表达不了时：
  1. 把本文件复制成 07_items.py（去掉下划线）
  2. 删掉同编号的 .yaml，避免编号重复
  3. 直接写 Python，只调用 components，不手写 HTML 标签

特殊 tab 清单仍待定，所以当前 11 个 tab 全部由 .yaml 驱动。
"""
from workbench.core import components as c
from workbench.core.templates import Tab

no = "07"
name = "板书条目与证据"
short = "条目"


def render(ctx) -> str:
    cards = []
    for it in ctx.manifest.get("items", []):
        frame = ctx.asset(it["frame"], caption="原帧", group="items")
        crop = ctx.asset(it["crop"], caption="裁剪", group="items")
        cards.append(c.evidence_card(
            item_id=it["item_id"],
            text=it["text"],
            span=(it["first_seen_sec"], it["last_seen_sec"]),
            frame=frame,
            crop=crop,
            ocr_link=f"#06",
            status=it.get("status", "done"),
        ))
    return c.card_stack(
        c.card("条目证据", c.card_grid(cards), badge=f"{len(cards)} 条"),
        c.details("归并规则", "同一文本连续出现时合并，记录首见 / 末见时间。"),
    )


TAB = Tab(no=no, name=name, short=short, render=render)
