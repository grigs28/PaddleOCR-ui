# 更新日志

本文件记录 PaddleOCR Web UI 的版本变更。
格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。
**版本号规则：UI 顶栏版本号自动读取本文件中最新一个 `## [x.y.z]` 条目。**

## [1.3.0] - 2026-11-23

### 新增
- UI 顶栏新增「API 说明」页：API Key 获取、任务 API、文档转换 API、DWG/DXF 调用示例
- API 文档固定生产地址 `http://192.168.0.8:5553/`，补充 API Key 获取方式和 DWG/DXF 说明

## [1.2.0] - 2026-11-23

### 新增
- 非图片型 PDF 直转 DOCX：有文本层的 PDF 使用 exactdoc（refine 3）直接生成 DOCX，保留原版式、图片、页眉页脚和活动页码
- 文档转换 API `POST /api/v1/convert/markdown`：DOCX/DOC 同步返回 Markdown；PDF 创建异步任务
- 文档转换 API `POST /api/v1/convert/docx`：DOC/DOCX/ODT/RTF 直接返回 DOCX
- DOCX/DOC 直转 Markdown：Pandoc 保留标题/列表/表格，图片内联为 data URI
- DOC/DOCX + docx 输出：LibreOffice 直转/复制，不再走 OCR
- 管理面板新增 PDF→DOCX 精修轮数、最大页数、转换超时配置

### 变更
- `output_formats` 含 `docx` 的 PDF 任务，DOCX 生成由 Markdown 转换改为 exactdoc 直转；图片型 PDF 仍走 OCR→Markdown→DOCX
- Office 任务（doc/docx + 仅 docx/markdown）走快速路径，不调用 OCR 引擎
- Docker 构建 pip 通过 BuildKit secret 注入 TLS 代理根 CA
- 新增依赖 `exactdoc==0.3.0b3`（Apache-2.0）

### 修复
- `.env` 大小写键重复导致同名配置互相覆盖；启动同步和管理面板写回统一使用大写键
- DOCX 下载优先返回任务结果目录中已保存的 `result.docx`，避免 exactdoc 直转产物被 Markdown 重新生成覆盖
- DOCX→Markdown 图片内联增加路径包含检查和大小上限，并拒绝解压后超过 500MB 的 DOCX，修复潜在任意文件读取与压缩炸弹
- Office 同步转换增加 Pandoc 硬超时和 2 并发上限，避免绕过任务队列打满 CPU
- 新增 `OFFICE_MARKDOWN_TIMEOUT` 配置

## [1.1.2] - 2026-09-09

### 新增
- MinerU 任务进度实时回传：原生进度映射到 10%~90% 区间，前端进度条连续走动（此前全程卡在 10%）
- 转换队列标题显示成功/失败计数（绿色成功数、红色失败数）

## [1.1.1] - 2026-09-09

### 新增
- 系统日志页支持级别筛选（全部 / INFO / WARNING / ERROR）

### 变更
- 系统日志页打开和刷新时自动滚动到底部显示最新日志；上翻阅读历史时暂停跟随，右下角可一键回到底部

### 修复
- 容器时区 UTC → Asia/Shanghai（此前日志时间戳和任务时间比实际慢 8 小时）

## [1.1.0] - 2026-09-09

### 新增
- 顶栏显示版本信息（UI 版本 + PaddleOCR-VL-1.6-0.9B 引擎版本），点击查看更新日志
- 管理面板新增 MinerU 设置区：服务地址（带测试连接）、上传超时、轮询超时、轮询间隔、单次查询超时，全部热生效

### 变更
- MinerU 上传超时 120s → 600s（可配置）
- MinerU 轮询超时 3600s → 1800s（可配置）
- MinerU 轮询间隔 5s → 3s（可配置）

### 修复
- MinerU 轮询连续 10 次 404 时立即判定服务端任务丢失并失败，不再空等整个轮询超时（此前任务空转 43 分钟才失败）
- 管理面板在线配置改为直接写宿主机 `.env`（容器内挂载），容器重建后配置不再丢失
- 新增 `.dockerignore`，镜像不再包含 `__pycache__` 等缓存文件

## [1.0.0] - 2026-06-18

### 初始版本
- 三引擎 OCR：PaddleOCR-VL-1.6（高精度模式）/ MinerU / PP-OCRv6
- 支持 PDF / 图片 / Office 文档 / CAD 图纸（DWG/DXF）识别
- 3 级优先级任务队列（管理员 > API > 普通用户）+ 按文件类型分信号量并发控制
- OOS SSO 登录 + API Key 双认证
- WebSocket 实时进度推送 + 轮询降级
- 结果导出 Markdown / TXT / DOCX / JSON
- 管理后台：用户管理、系统设置、日志查看
