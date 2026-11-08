# 板书数字化 UI 方向稿

根据 [项目架构设计](../项目架构设计.md) 使用内置 image gen 生成。每张包含 Web 结果页、小程序课程列表与笔记详情，共三套方向、九个界面。属于静态视觉探索，尚未实现交互或连接后端。产品名「板书拾记」、课程、板书、时间与数量均为演示内容；图中文字和数学公式需在实现时校对。

- [A 清爽蓝白](./A-clean-blue.png)：白底、蓝色操作、清晰分栏，适合作为低成本前端原型的基础。
- [B 纸感学术](./B-academic-paper.png)：米白、墨绿、阅读排版，偏重笔记阅读。
- [C 深色青绿](./C-dark-jade.png)：深灰、青绿、视频与时间轴，偏重课堂回看与演示。

## 复刻实现

- [B 纸感学术](./B/)：已按原图复刻为静态页面（零依赖、双击可看）——[web.html](./B/web.html) Web 结果页、[mini-course.html](./B/mini-course.html) 小程序课程页、[mini-note.html](./B/mini-note.html) 小程序笔记页；共享设计令牌与公式/黑板组件在 [B/base.css](./B/base.css)。公式为手写 CSS 排版，黑板画面纯 CSS 绘制，数据为写死的演示内容。
- [B 整合分享版](./B/share-all-in-one.html)：把上面 4 个文件内联为**单个自包含 HTML**，可直接作为附件发送。内置「全部预览 / 课程 / 笔记 / Web」切换、自动等比缩放、界面间联动跳转（课程→笔记→原始板书）、板书证据点击跳时间点；支持 `#course` / `#note` / `#web` / `#all` 后缀定位，浏览器打印可导出含三页的 PDF。视觉与三个原页面一致，仍为零外部依赖。

## 生成提示词

共同提示：Generate a high-fidelity Chinese classroom blackboard digitization UI board named 板书拾记. One large desktop web result workspace on the left and two WeChat mini program screens on the right: course list and note detail. Workflow: upload classroom video, processing status, extracted notes, source blackboard evidence per note, export PDF/TXT. Desktop: 高等数学·定积分, 演示数据 badge, realistic green chalkboard with handwritten math, selected evidence rectangle, timestamps, adjacent structured notes, 查看原始板书, evidence thumbnails, 上传视频 and 导出笔记. Mobile: native mini program header capsule, readable touch targets, 课程/笔记/我的 navigation, upload, evidence crop, export PDF. Consistent desktop/mobile design. No developer console, JSON, backend details, invented performance metrics, marketing slogans, perspective devices or illustrations.

- A style: snow white and cool gray, cobalt #2563EB, navy sans serif type, thin borders, restrained 10px radii, compact navigation, video left and notes right, practical educational application.
- B style: ivory #F7F4EA, forest green #285847, ink text, Song serif headings with sans serif controls, subtle ruled separators, scholarly editorial reading layout, no distressed texture.
- C style: graphite #14191B, charcoal #202729, jade #64D8B0, warm white text, thin slate dividers, restrained 6px radii, dominant chalkboard player, note timeline and adjacent notes, no neon glow or glassmorphism.
