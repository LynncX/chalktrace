"""工作台单文件生成器：manifest + 分区声明 → 一个 index.html。

素材三档由 --assets 控制（默认 tiered）：

    link    不塞媒体文件，全部走相对路径          —— 本地调试，HTML 最小
    inline  全塞，所有媒体 base64 内嵌            —— 分享，单文件最完整
    tiered  分级：<100KB 内联 / <2MB 缩略图兜底 / 更大只引用 —— 分享，默认

用法：
    python -m workbench.build --run demo_mock
    python -m workbench.build --run 20261107_a --assets link
    python -m workbench.build --run 20261107_a --assets inline
    python -m workbench.build --run demo_mock --assets tiered --out /tmp/wb.html
    python -m workbench.build --run 20261107_a --watch 1   # manifest 变更即重生成
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .core import assets, registry, shell
from .core.context import RunContext

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
FIXTURES = ROOT / "workbench" / "fixtures"
PARTITIONS = ROOT / "workbench" / "partitions"
STATIC = ROOT / "workbench" / "static"


def resolve_run(run_id: str) -> Path:
    p = Path(run_id)
    if p.is_dir():
        return p.resolve()
    for base in (RUNS, FIXTURES):
        cand = base / run_id
        if (cand / "manifest.json").is_file():
            return cand.resolve()
    raise FileNotFoundError(
        f"找不到 run {run_id!r}：期望 {RUNS / run_id / 'manifest.json'} 或直接传目录路径"
    )


def build(run_id: str, *, assets_mode: str = "tiered", out: str | None = None) -> dict:
    root = resolve_run(run_id)
    out_path = Path(out).resolve() if out else root / "index.html"
    ctx = RunContext(root, assets_mode=assets_mode, out_dir=out_path.parent)
    tabs = registry.discover(PARTITIONS, ctx)
    pairs = [(t, t.render(ctx)) for t in tabs]
    html = shell.wrap(
        title=str(ctx.manifest.get("title", "工作展示台")),
        tab_pairs=pairs,
        css=(STATIC / "theme.css").read_text(encoding="utf-8"),
        js=(STATIC / "app.js").read_text(encoding="utf-8"),
        payload=ctx.public_payload([t for t, _ in pairs]),
        meta=f"{ctx.assets_mode} · {len(tabs)} tabs",
        foot="由 workbench/build.py 生成 · 缺失产物一律显示占位，不补图不反推",
    )
    ctx.write(html, out_path.name)
    return {
        "path": out_path,
        "mode": ctx.assets_mode,
        "tabs": len(tabs),
        "bytes": out_path.stat().st_size,
        "embedded": html.count("data:"),
        "warnings": ctx.warnings,
    }


def _report(info: dict) -> None:
    size = info["bytes"] / 1024 / 1024
    print(f"[workbench] --assets={info['mode']:<6} tabs={info['tabs']:>2} "
          f"内嵌媒体={info['embedded']:>3} → {info['path']} ({size:.2f} MB)")
    for w in info["warnings"]:
        print(f"  ! {w}", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成工作展示台单文件 HTML")
    ap.add_argument("--run", default="demo_mock", help="run_id 或 run 目录路径（默认 demo_mock）")
    ap.add_argument("--assets", default="tiered",
                    choices=list(assets.MODES) + list(assets.MODE_ALIASES),
                    help="link=不塞(本地) / inline=全塞(分享) / tiered=分级(分享，默认)")
    ap.add_argument("--out", help="输出 HTML 路径（默认 runs/<run_id>/index.html）")
    ap.add_argument("--watch", type=float, default=0,
                    help="秒；轮询 manifest.json，变更即重生成（对应增量重生成）")
    args = ap.parse_args(argv)
    mode = assets.normalize_mode(args.assets)

    if args.watch > 0:
        mf = resolve_run(args.run) / "manifest.json"
        last = None
        print(f"[workbench] 监视 {mf}（Ctrl-C 退出）")
        try:
            while True:
                stamp = mf.stat().st_mtime_ns if mf.is_file() else 0
                if stamp != last:
                    _report(build(args.run, assets_mode=mode, out=args.out))
                    last = stamp
                time.sleep(args.watch)
        except KeyboardInterrupt:
            print("\n[workbench] 已停止")
        return 0

    _report(build(args.run, assets_mode=mode, out=args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
