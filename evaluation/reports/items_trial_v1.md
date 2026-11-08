# 跨帧条目跟踪验证

2026-11-08，视频 `data/videos/test_video.mp4`，配置 `evaluation/configs/gate_test_video.yaml`，使用遮挡与变化门控。

- `runs/items_trial_v1/` 完整执行视频采样、区域标定、人体遮挡、门控、PaddleOCR、条目与笔记阶段。候选 6 帧；实际 OCR 为 150、155、165 秒，合计 13 框。首次跟踪结果为 7 条。
- 人工检查识别历史发现：第二行在 155 秒被识别成前后两个框，165 秒恢复长框。仅与末次片段比较会重复建条目。补充同时与既有最佳版本比较，并加入“完整行→半行→完整行”回归测试。
- `runs/items_replay_v2/` 使用相同的真实 OCR 框和证据，只回放最终 07/08 算法；该运行的 01–06 保持 pending，不声称重新执行 OCR 或比较推理耗时。13 个框形成 6 条，7 次观察归入已有条目。

| 条目 | 观察时间（秒） | 次数 | 最佳原文概要 |
|---|---|---|---|
| IT-0001 | 150–165 | 3 | Monetary Policy;the branch… |
| IT-0002 | 150–165 | 3 | the money supply…aggregate market |
| IT-0003 | 150–165 | 3 | and manage the economy. |
| IT-0004 | 155–155 | 1 | the money supply in a societv |
| IT-0005 | 155–165 | 2 | .Handled by the central bank |
| IT-0006 | 165–165 | 1 | .In the U.s., it's called the Feo |

IT-0004 是 OCR 拆行导致的残余重复；本版一对一行框跟踪没有解决一对多行拆分。IT-0002 最佳版本仍有 `regu` 等缺字；置信度和长度不能替代正确率。IT-0006 的 `Feo` 原样保留，没有自动改写。6 条是算法输出数量，不是人工真值条目数，也不代表准确率。

每条绑定最佳观察时间、原始帧、映射后的标框、实际 OCR 输入裁剪以及全部版本历史。输出 `08_notes/notes.md`、`notes.txt`，并以 `raw.md` 保留逐次原文。验证产物契约通过，工作台可生成并展开历史。

运行方式见 [跨帧条目跟踪](../../docs/跨帧条目跟踪.md)。运行产物与模型缓存不进入 Git；跟踪规则和已知限制均在文档及每次运行的 `07_items/rules.json` 中保存。
