"""固定标定下的保守行级跟踪；保留观察历史，不推断擦除或拼造文字。"""
from difflib import SequenceMatcher
import math
import unicodedata

import cv2
import numpy as np

from ..contracts import BoardItem, OcrBox


RULES = dict(text_similarity=.72, min_shared_chars=4, axis_overlap=.5,
             max_missing_calls=2, max_gap_s=120, confidence_slack=.10)


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def bounds(poly):
    points = np.asarray(poly, dtype=float)
    return [math.floor(points[:, 0].min()), math.floor(points[:, 1].min()),
            math.ceil(points[:, 0].max()), math.ceil(points[:, 1].max())]


def affinity(a, b):
    """同行且水平重叠才比较文字；短文本只允许完整相等。"""
    aa, bb = bounds(a["poly"]), bounds(b["poly"])
    for lo, hi in ((0, 2), (1, 3)):
        overlap = max(0, min(aa[hi], bb[hi]) - max(aa[lo], bb[lo]))
        if overlap / max(1, min(aa[hi]-aa[lo], bb[hi]-bb[lo])) < RULES["axis_overlap"]:
            return 0
    x, y = normalize(a["text"]), normalize(b["text"])
    if not x or not y:
        return 0
    if x == y:
        return 1.0
    if min(len(x), len(y)) < RULES["min_shared_chars"]:
        return 0
    similarity = SequenceMatcher(None, x, y, autojunk=False).ratio()
    if x in y or y in x:
        # 太短的公共前缀不足以确认同一条板书。
        similarity = max(similarity, .9 if min(len(x), len(y))/max(len(x), len(y)) >= .45 else 0)
    return similarity if similarity >= RULES["text_similarity"] else 0


def best_observation(observations):
    highest = max(b["score"] for b in observations)
    eligible = [b for b in observations if b["score"] >= highest-RULES["confidence_slack"]]
    return max(eligible, key=lambda b: (len(normalize(b["text"])), b["score"]))


def merge_items(boxes, calls):
    """全局候选按相似度贪心一对一；空 OCR 调用也计入缺失窗口。"""
    tracks = []
    for sequence, call in enumerate(calls):
        current = sorted((b for b in boxes if b["ocr_call"] == call["call"] and normalize(b["text"])),
                         key=lambda b: (bounds(b["poly"])[1], bounds(b["poly"])[0]))
        candidates = []
        for i, track in enumerate(tracks):
            previous = track["observations"][-1]
            if (sequence-track["sequence"] > RULES["max_missing_calls"] + 1 or
                    call["ts"]-previous["ts"] > RULES["max_gap_s"]):
                continue
            for j, box in enumerate(current):
                score = max(affinity(previous, box), affinity(best_observation(track["observations"]), box))
                if score:
                    candidates.append((-score, i, j))
        assigned, used = {}, set()
        for negative_score, i, j in sorted(candidates):
            if i not in used and j not in assigned:
                assigned[j] = (i, -negative_score)
                used.add(i)
        for j, box in enumerate(current):
            if j in assigned:
                i, similarity = assigned[j]
                track = tracks[i]
            else:
                similarity = None
                track = dict(item_id=f"IT-{len(tracks)+1:04d}", observations=[])
                tracks.append(track)
            track["sequence"] = sequence
            track["observations"].append(dict(box, match_similarity=similarity))
    for track in tracks:
        observations = track["observations"]
        track["best"] = best_observation(observations)
    return tracks


def bind_evidence(tracks, writer):
    items = []
    for track in tracks:
        best = track["best"]
        item_id = track["item_id"]
        source = cv2.imread(str(writer.root / best["source_path"]))
        board = cv2.imread(str(writer.root / best["input_path"]))
        if source is None or board is None:
            raise RuntimeError(f"条目证据缺失：{item_id}")
        x1, y1, x2, y2 = bounds(best["poly"])
        h, w = board.shape[:2]
        crop = board[max(0, y1-4):min(h, y2+5), max(0, x1-4):min(w, x2+5)]
        if not crop.size:
            raise ValueError(f"条目坐标超出 OCR 输入：{item_id}")
        crop_path = f"media/07_items/crop_{item_id}.png"
        frame_path = f"media/07_items/box_{item_id}.png"
        history_path = f"07_items/history/{item_id}.json"
        cv2.polylines(source, [np.rint(best["source_poly"]).astype("int32")], True, (0, 200, 255), 3)
        writer.save_image(frame_path, source)
        writer.save_image(crop_path, crop)
        writer.write_json(history_path, track)
        observations = track["observations"]
        item = BoardItem(item_id=item_id, text=best["text"], first_seen_sec=observations[0]["ts"],
                         last_seen_sec=observations[-1]["ts"], frame=frame_path, crop=crop_path,
                         ocr_link="#06", bbox=[x1, y1, x2-x1, y2-y1], best=OcrBox.from_dict(best),
                         evidence=dict(history=history_path, source=best["source_path"],
                                       input=best["input_path"]),
                         _extra=dict(observations=len(observations), bbox_space="board"))
        writer.write_item(item)
        items.append(item.to_dict())
    writer.write_json("07_items/items.json", items)
    writer.write_json("07_items/rules.json", RULES)
    return items
