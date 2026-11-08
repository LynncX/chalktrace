"""去重笔记与逐帧原文并存，OCR 原文使用自适应围栏避免 Markdown 注入。"""
import re


def fenced(text):
    fence = "`" * max(3, max((len(s) for s in re.findall(r"`+", text)), default=0)+1)
    return f"{fence}\n{text}\n{fence}"


def write_notes(items, calls, writer):
    lines = ["# 去重板书笔记", "", "按首次观察排序；保留最佳识别原文，不自动纠错。时间仅表示采样观察范围，不代表书写起止。", ""]
    plain = []
    if not items:
        message = ("本次没有执行 OCR" if not calls else "本次没有可用文字条目") + "：请查看 OCR 与门控记录，不能据此认为视频没有板书。"
        lines.append(message)
        plain.append(message)
    for item in items:
        span = f"{item['first_seen_sec']:.2f}–{item['last_seen_sec']:.2f}s"
        best = item["best"]
        lines.extend([f"## {item['item_id']} · {span}", "", fenced(item["text"]), "",
                      f"最佳观察：{best['ts']:.2f}s · frame {best['frame']} · OCR {best['ocr_call']}", "",
                      f"[原帧](../{item['evidence']['source']}) · [标框](../{item['frame']}) · "
                      f"[裁剪](../{item['crop']}) · [识别历史](../{item['evidence']['history']})", ""])
        plain.append(f"[{item['item_id']} · {span}]\n{item['text']}")
    raw = ["# 逐帧 OCR 原文", ""]
    for call in calls:
        raw.extend([f"## {call['ts']:.2f}s · frame {call['frame']}", "",
                    fenced(call["text"] or "（未识别出文字）"), ""])
    writer.write_text("08_notes/raw.md", "\n".join(raw))
    writer.write_text("08_notes/notes.md", "\n".join(lines))
    writer.write_text("08_notes/notes.txt", "\n\n".join(plain)+"\n")
    writer.set_outputs(dict(notes_md="08_notes/notes.md", notes_txt="08_notes/notes.txt",
                            raw_ocr="08_notes/raw.md", ocr_boxes="06_ocr/boxes.json",
                            items="07_items/items.json"))
    writer.finish_stage("08", metrics=dict(sections=len(items), chars=sum(len(i["text"]) for i in items)),
                        note="位置与文字匹配去重；绑定最佳原文和证据；保留逐帧 raw.md；未纠错或导出 PDF")
