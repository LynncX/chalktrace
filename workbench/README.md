# workbench/

把 `runs/<run_id>/` 渲染成可双击打开的**单个 `index.html`** 工作展示台。只读产物：不跑 CV、不生成或补写产物、不反推缺失数据；文件引用不到就显示「缺失」占位。

## 契约

`cv_engine` 逐阶段写入一次运行目录，工作台只认：

- `runs/<run_id>/manifest.json`（唯一数据入口）
- 其中引用的产物文件，路径均相对该 run 目录

字段名与路径名硬编码在 `workbench/partitions/*.yaml`，改名需同步改 YAML。可照抄的样例：`workbench/fixtures/demo_mock/manifest.json`。manifest 其余字段页面不消费，可自由扩展。

## manifest.json

| 字段 | 内容 |
|---|---|
| `run_id` `title` | 运行标识、页面标题 |
| `video` | `frames` `duration_s`（`name` `fps` 备用） |
| `stages` | 键 `"01"`–`"09"`，值 `{name, status, metrics}`；`status` ∈ `done`/`running`/`pending`，驱动页签三态 |
| `items[]` | `item_id` `text` `first_seen_sec` `last_seen_sec` `frame` `crop` `ocr_link` `status`（07 条目证据卡） |
| `compare[]` | 行对象，列名见 `partitions/10_compare.yaml` |
| `files[]` | `{path, size}`，总览产物索引 |

指标按点号路径取值（`stages.01.metrics.sampled`、`video.frames`、`items|len`），实际键名见各 YAML 的 `metrics.key`。

## 产物文件

- 数据表：`01_frames/frames.json`、`04_gate/gate.json`、`06_ocr/calls.json`、`09_stats/summary.json`；对象数组或 `{"rows": [...]}`，列名见对应 YAML 的 `tables.columns`。
- 文本：`08_notes/notes.md`，内联展示正文。
- 媒体：`media/<stage>/...` 与 `items[].frame` / `.crop`；视频可配 `poster`。图片、视频须真实落盘。
- 图位：`partitions/*.yaml` 里 `path:` 指定单文件，`glob:`（相对 run 目录）自动收录该目录下的全部真实媒体，按文件名自然序、`limit` 上限（默认 24）。产物放进 `media/<stage>/` 即自动出现在对应 tab，无需改 workbench；`glob` 扫不到文件时不渲染任何占位，显式 `path` 缺失才显示「缺失」。

## 实现标注

`workbench/annotations/stages.yaml` 按 stage 编号记录对应的代码文件、核心函数、核心参数与备注，渲染为各 tab 底部默认折叠的「实现标注」。与 manifest 解耦，`cv_engine` 实现完成后只需校准该文件；tab 配置可写 `annotations: false` 关闭、`annotations: open` 默认展开。

## 单阶段实验

单独优化某个 stage 时，写 `experiments/<exp_id>/manifest.json` 并加 `"kind": "experiment"`，页面自动改用 `partitions_experiment/`（列=变体、行=同一样本、图片等尺寸对齐）。字段：`stage_name`、`samples[]`（`id` / `title`）、`variants[]`（`id` / `name` / `params` / `images`{样本 id: 路径} / `captions`）、`winner`、`compare[]`；样例见 `workbench/fixtures/demo_experiment/manifest.json`。

实验**不改变上面的 run 契约**：`kind` 缺省即 `run`。媒体仍走同一素材层，实验默认 `--assets link`（本地盯图），要发群里评审才用 `tiered`。选中变体后把参数校准到 `annotations/stages.yaml`、再跑一次完整 run，实验目录可整个删掉。

## 生成

```bash
pip install -r workbench/requirements.txt
python -m workbench.build --run <run_id>             # → runs/<run_id>/index.html
python -m workbench.build --run <exp_id>             # 实验 → experiments/<exp_id>/index.html
python -m workbench.build --run <run_id> --watch 1   # manifest 变更即重生成
```

`--run` 也可直接传目录路径。每完成一个 stage 更新一次 manifest（含 `status`），配合 `--watch` 得到实时进度页。`--assets tiered|link|inline` 只控制媒体是否内嵌：run 默认 `tiered`，实验默认 `link`；不改变上述契约。
