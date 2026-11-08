"""区域核验：按同一帧配对标定图与输出图，只消费落盘元数据。"""
from workbench.core import components as c
from workbench.core.context import Metric

no = "02"
name = "白板区域核验"
short = "白板"

MODES = {"manual_roi": "人工矩形 ROI · 裁剪", "manual_corners": "人工四角 · 透视校正",
         "full_frame": "全帧直通 · 未定位"}


def render(ctx):
    rows = ctx.read_json("02_board/calibration.json")
    if not isinstance(rows, list):
        rows = []
    modes = list(dict.fromkeys(MODES.get(row.get("mode"), "来源未知") for row in rows))
    metrics = [Metric("人工标定帧", str(sum(row.get("mode") in ("manual_roi", "manual_corners") for row in rows)) if rows else "—"),
               Metric("全帧直通帧", str(sum(row.get("mode") == "full_frame" for row in rows)) if rows else "—")]
    parts = [c.stage_header(no, name, ctx.status_of(no)), c.metric_row(metrics),
             c.card("区域来源 · " + (" / ".join(modes) if modes else "缺失"), c.details("如何核验", "每组依次展示原视频画面的标定叠加图和对应输出图：区域外压暗，黄色线表示边界，红色角点按 1 左上、2 右上、3 右下、4 左下编号，坐标属于原视频帧。输出图区分裁剪、透视校正和全帧直通。全帧直通不会移除教师，人工标定也不等于自动定位。", open=True))]
    if not rows:
        parts.append(c.missing_card("区域标定记录", "本次运行没有 calibration.json；不能推断定位来源或置信度。"))
    for row in rows[:18]:
        mode = row.get("mode")
        group = f"board-{row.get('frame', '')}"
        figures = []
        for field, caption in (("overlay_path", "原图标定 · 边界与四角"),
                               ("path", "透视校正结果" if mode == "manual_corners" else
                                "裁剪结果" if mode == "manual_roi" else "全帧直通结果")):
            if row.get(field):
                figures.append(c.asset_figure(ctx.asset(row[field], caption=caption, group=group)))
            else:
                figures.append(c.missing_card(caption, "未记录产物路径；不推测文件名。"))
        title = f"{row.get('ts', '—')}s · 帧 {row.get('frame', '—')} · {MODES.get(mode, '来源未知')}"
        parts.append(c.card(title, c.board_pair(figures)))
    if rows:
        table = []
        for row in rows:
            table.append({"帧": row.get("frame"), "时间/s": row.get("ts"),
                          "来源": MODES.get(row.get("mode"), "来源未知"),
                          "四角坐标（原帧）": str(row.get("corners", "缺失")),
                          "输出宽×高": str(row.get("output_size", "缺失"))})
        parts.append(c.details("坐标约定", "原点为原视频画面左上角，x 向右、y 向下；矩形 ROI 使用像素宽高，右下角为 x+width−1、y+height−1。完整变换矩阵见文件索引中的 02_board/calibration.json。"))
        parts.append(c.table(table, title="标定记录 · 原视频像素坐标"))
    return c.card_stack(*parts)
