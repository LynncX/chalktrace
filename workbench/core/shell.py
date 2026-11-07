"""页面骨架装配：读 static/shell.html 模板，把 CSS / JS 内联进单文件。

源码里 CSS/JS 独立维护，产物仍是一个 index.html。
Python 侧不拼 HTML 标签（标签只在 components.py 与静态模板里）。
"""
from __future__ import annotations

import json
from pathlib import Path

from . import components as c

STATIC = Path(__file__).resolve().parent.parent / "static"

_TOKENS = ("TITLE", "EYEBROW", "META", "CSS", "NAV", "PANELS", "FOOT", "PAYLOAD", "JS")


def wrap(*, title: str, tab_pairs: list, css: str, js: str,
         payload: dict, eyebrow: str = "工作展示台", meta: str = "",
         foot: str = "") -> str:
    tpl = (STATIC / "shell.html").read_text(encoding="utf-8")
    nav = "".join(c.tab_button(t.no, t.short, active=i == 0)
                  for i, (t, _) in enumerate(tab_pairs))
    panels = "".join(c.tab_panel(t.no, body, active=i == 0)
                     for i, (t, body) in enumerate(tab_pairs))
    values = {
        "TITLE": title,
        "EYEBROW": eyebrow,
        "META": meta,
        "CSS": css,
        "NAV": nav,
        "PANELS": panels,
        "FOOT": foot,
        "PAYLOAD": json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c"),
        "JS": js,
    }
    for key in _TOKENS:
        tpl = tpl.replace("{{WB_" + key + "}}", values[key])
    return tpl
