# 板书拾记

固定机位课堂视频 → 白板区域 → 遮挡/变化门控 → OCR → 跨帧条目 → 带证据的去重笔记。

```sh
pixi install
pixi run serve
```

打开 http://127.0.0.1:8001 ，选择视频、框选白板区域、提交任务，即可查看进度、笔记与证据，并下载 Markdown / TXT。默认仅采样 3 帧，首次建议用短片试跑。OCR 模型首次使用需下载，缓存统一放在 `.cache/`。

- [Web 操作与验证](server/README.md)
- [当前进度与限制](docs/STATUS.md)
- [算法 CLI](docs/算法最小闭环.md)
- [只读算法工作台](workbench/README.md)
- [人工标注工作台](annotation_workbench/README.md)

当前为本地单用户版本。识别文字保留原文，需要结合视频和证据核验；尚不支持自动纠错、公式重排或 PDF 导出。
