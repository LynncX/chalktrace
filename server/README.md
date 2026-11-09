# 板书拾记 Web 最小闭环

在项目根目录运行：

```sh
pixi run serve
# 端口冲突时
pixi run serve --port 8010
```

默认打开 http://127.0.0.1:8001 。只绑定回环地址，面向本机单用户；没有账号和远程访问认证。请使用单个服务进程，不启用多 worker 或自动 reload。

## 操作

- 选择视频；浏览器预览推荐 H.264 MP4。拖动预览滑块选择参考帧，再拖动框选固定白板区域；不选时明确使用全帧。
- 设置起止秒数、采样间隔、候选帧上限及门控方式。默认固定采样、5 秒间隔、最多 3 帧；长视频不会默认全量处理。
- 提交后显示上传进度、排队/运行状态和各阶段状态。OCR 初始化较慢，阶段进度不是剩余时间估算。
- 完成后点击左侧板书条目，查看原文、裁剪、原帧标框，并跳转视频的最佳观察时间。下载 Markdown / TXT。
- 主页列出历史任务；任务 URL 的 hash 保存任务 ID，刷新可恢复。失败任务显示原因，可新建任务重新提交。

## 边界与数据

- `app.py` 提供同源静态页与 API，`jobs.py` 用 SQLite 和一个后台队列管理任务；每次算法运行使用独立 Python 子进程，沿用 CLI、配置和 manifest。
- 上传视频、配置、worker 日志及 SQLite 在 `../data/jobs/`；算法产物在 `../runs/<job_id>/`，均不入库。停止服务并确认无需历史记录后可删除对应任务目录及运行目录；SQLite 元数据仍会保留，因此清理全部历史时一并删除 `data/jobs/`。
- 重启时未完成任务标记失败；正常退出会等待已提交任务结束。没有取消、自动重试或断点续跑。
- `GET /api/jobs`、`POST /api/jobs`、`GET /api/jobs/{id}`、`GET /api/jobs/{id}/video`、`GET /api/runs/{id}/manifest`、`GET /api/runs/{id}/files/{path}`、`GET /api/health`。
- 产物只从 manifest 的 `files` 白名单提供；视频支持 Range。没有开放任意本机路径或 CLI 历史运行的浏览接口。
- 原型中的课程章节改用真实板书条目。当前没有课程管理、自动章节、文字纠错、公式重排、PDF 或小程序。Markdown 保留运行目录相对证据链接，单独下载后如需打开这些链接，应同时保留对应产物目录。

## 验证

```sh
pixi run python -m unittest discover -s server/tests -v
# 服务已启动，Node 和现有 Chrome 可用时；会真实提交任务并调用 OCR
node server/tests/browser_smoke.mjs --url http://127.0.0.1:8001 --video /absolute/path/to/short.mp4 --screenshot /tmp/web-product.png
```

浏览器脚本使用现有 Chrome DevTools 协议，没有额外安装浏览器或 Node 包；验证上传、ROI、真实 OCR、证据加载、跳转、下载和刷新恢复。测试素材需为可解码、可被 Chrome 播放且有板书文字的短视频。
