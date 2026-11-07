"""工作台单文件生成器：manifest + 分区声明 → 一个 index.html。

manifest.kind 决定页面类型（缺省 run，完全向后兼容）：
    run         流水线全貌 → partitions/             默认 --assets tiered
    experiment  单阶段实验 → partitions_experiment/  默认 --assets link

素材三档由 --assets 控制：
    link    不塞媒体文件，全部走相对路径          —— 本地调试，HTML 最小
    inline  全塞，所有媒体 base64 内嵌            —— 分享，单文件最完整
    tiered  分级：<100KB 内联 / <2MB 缩略图兜底 / 更大只引用 —— 分享

用法：
    python -m workbench.build --run demo_mock
    python -m workbench.build --run 20261107_a --assets link
    python -m workbench.build --run demo_experiment                    # 实验页，默认 link
    python -m workbench.build --run demo_experiment --assets tiered    # 发群里评审
    python -m workbench.build --run experiments/exp_ocr_01             # 也可直接传目录
    python -m workbench.build --run 20261107_a --watch 1
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .core import assets, registry, shell
from .core.context import RunContext

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
EXPERIMENTS = ROOT / "experiments"
FIXTURES = ROOT / "workbench" / "fixtures"
PARTITIONS = ROOT / "workbench" / "partitions"
EXPERIMENT_PARTITIONS = ROOT / "workbench" / "partitions_experiment"
STATIC = ROOT / "workbench" / "static"


def resolve_run(run_id: str) -> Path:
    p = Path(run_id)
    if p.is_dir():
        return p.resolve()
    for base in (RUNS, EXPERIMENTS, FIXTURES):
        cand = base / run_id
        if (cand / "manifest.json").is_file():
            return cand.resolve()
    raise FileNotFoundError(
        f"找不到 {run_id!r}：期望 runs/<id>/manifest.json、experiments/<id>/manifest.json 或直接传目录路径"
    )


def manifest_kind(root: Path) -> str:
    """缺省 run；不认识的 kind 一律按 run 处理，保证旧契约永不受影响。"""
    mf = root / "manifest.json"
    if mf.is_file():
        try:
            return str(json.loads(mf.read_text(encoding="utf-8")).get("kind") or "run")
        except (OSError, ValueError, AttributeError):
            pass
    return "run"


def build(run_id: str, *, assets_mode: str | None = None, out: str | None = None) -> dict:
    root = resolve_run(run_id)
    kind = manifest_kind(root)
    is_exp = kind == "experiment"
    # 实验默认本地盯图（link）；run 默认分级分享档。显式传 --assets 时以显式为准。
    if assets_mode is None:
        assets_mode = "link" if is_exp else "tiered"
    out_path = Path(out).resolve() if out else root / "index.html"
    ctx = RunContext(root, assets_mode=assets_mode, out_dir=out_path.parent)
    partitions = EXPERIMENT_PARTITIONS if is_exp else PARTITIONS
    tabs = registry.discover(partitions, ctx)
    pairs = [(t, t.render(ctx)) for t in tabs]
    html = shell.wrap(
        title=str(ctx.manifest.get("title", "工作展示台")),
        tab_pairs=pairs,
        eyebrow="单阶段实验" if is_exp else "工作展示台",
        css=(STATIC / "theme.css").read_text(encoding="utf-8"),
        js=(STATIC / "app.js").read_text(encoding="utf-8"),
        payload=ctx.public_payload([t for t, _ in pairs]),
        meta=f"{kind} · {ctx.assets_mode} · {len(tabs)} tabs",
        foot=("由 workbench/build.py 生成 · 实验为过程证据，选中变体后校准 annotations/stages.yaml"
              if is_exp else
              "由 workbench/build.py 生成 · 缺失产物一律显示占位，不补图不反推"),
    )
    ctx.write(html, out_path.name)
    return {
        "path": out_path,
        "kind": kind,
        "mode": ctx.assets_mode,
        "tabs": len(tabs),
        "bytes": out_path.stat().st_size,
        "embedded": html.count("data:"),
        "warnings": ctx.warnings,
    }


def _report(info: dict) -> None:
    size = info["bytes"] / 1024 / 1024
    print(f"[workbench] kind={info['kind']:<10} --assets={info['mode']:<6} "
          f"tabs={info['tabs']:>2} 内嵌媒体={info['embedded']:>3} "
          f"→ {info['path']} ({size:.2f} MB)")
    for w in info["warnings"]:
        print(f"  ! {w}", file=sys.stderr)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成工作展示台单文件 HTML")
    ap.add_argument("--run", default="demo_mock", help="run_id 或目录路径（默认 demo_mock）")
    ap.add_argument("--assets", default=None,
                    choices=list(assets.MODES) + list(assets.MODE_ALIASES),
                    help="link=不塞(本地) / inline=全塞(分享) / tiered=分级(分享)；"
                         "缺省时 run=tiered、实验=link")
    ap.add_argument("--out", help="输出 HTML 路径（默认 <run>/index.html）")
    ap.add_argument("--watch", type=float, default=0,
                    help="秒；轮询 manifest.json，变更即重生成（对应增量重生成）")
    args = ap.parse_args(argv)
    mode = assets.normalize_mode(args.assets) if args.assets else None

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
