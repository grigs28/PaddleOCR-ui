# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 快速命令

```bash
# 后端
pip install -r requirements.txt
python -m backend.init_db                                  # 初始化数据库（建表 + 默认配置）
python -m backend.main                                     # 开发模式（reload=True，端口取 APP_PORT）
uvicorn backend.main:app --host 0.0.0.0 --port 5553        # 生产模式

# 前端
cd frontend && npm install
npm run dev                                                # 开发服务器 :3000，Vite 代理 /api /auth /ws 到 :5553
npm run build                                              # 产物输出到 frontend/dist/

# Docker（构建镜像前必须先生成 frontend/dist/，Dockerfile 会 COPY 到 /app/static）
# 本机网络经过 TLS 代理，构建时需注入代理根 CA（BuildKit secret）：
cd frontend && npm run build
docker build --secret id=tproxy_ca,src=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem \
  -t paddleocr-ui:latest -f docker/Dockerfile .
cd docker && docker compose up -d

# 一键启动：检查 .env、构建前端、初始化数据库，最后以单 worker 启动
bash start.sh
```

**没有测试套件**：仓库不包含单元测试、lint 或类型检查配置；`.test/` 目录只是临时试算脚本（且被 `.gitignore` 排除）。验证改动只能手动运行服务。

## 运行硬约束

- **必须单 worker**（`--workers 1`）。Session 存在进程内字典 `_sessions`（`backend/auth/session.py`），任务引擎、信号量、WebSocket 连接表也都是进程内单例。多 worker 会造成登录态丢失、进度推送串不到、队列重复消费。
- **`.env` 是唯一运行时配置源**。启动时 `main.py::_sync_env_file()` 把 `Settings` 中缺失的字段补写进 `.env`；管理面板改配置直接写回 `.env`（Docker 中 `../.env` 挂载到 `/app/.env`，容器重建不丢）。
- **前后端同源部署**。`backend/main.py` 在所有路由之后挂载静态目录：优先 `static/`，不存在则回退 `frontend/dist/`，并强制 `Cache-Control: no-cache`。`static/`、`frontend/dist/` 都被 gitignore。

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | FastAPI (Python 3.12+) — `backend/main.py` |
| 数据库 | PostgreSQL / openGauss-lite，SQLAlchemy 2.0 async + asyncpg |
| 前端 | Vue 3 + Element Plus + Pinia + Vue Router + Vite — `frontend/` |
| OCR 引擎 | 三选一：MinerU（默认）/ PaddleOCR-VL-1.6 HPS / PP-OCRv6 |
| CAD 转换 | ACADxPDF 服务（异步轮询）→ PDF + DXF；本地 `bin/cad2x` 回退 |
| DXF 文字 | ezdxf 直接提取文字实体（不走 OCR） |
| 文档转换 | LibreOffice headless → PDF；无 LO 时 docx/xlsx 降级 Python 提取 |
| 登录 | OOS SSO（Cookie session）+ API Key 双认证 |
| 实时推送 | WebSocket（仅 Cookie 会话）+ HTTP 轮询降级 |

## 架构核心

### 任务引擎 (`backend/services/task_engine.py`)

- `asyncio.PriorityQueue`，入队元素 `(-priority, 入队序号, task_id)`，数字越大优先级越高：管理员 2 > API Key 1 > 普通用户 0；同优先级 FIFO。
- 一个 `_worker` 循环出队后 `asyncio.create_task` 立即派发，真正的并发上限由三个 `asyncio.Semaphore` 控制：`image_semaphore`、`pdf_semaphore`、`acad_semaphore`。CAD 任务和「PDF→DWG 纯转换」都走 ACAD 信号量。
- 启动时 `_recover_stuck_tasks()` 把数据库中 `pending/queued/processing` 的任务重新入队。
- 两条处理路径：
  - `_process_task()` — `vl16`（PaddleOCR-VL）流程，含 Office/CAD 转 PDF、DXF 提取、图片提取、多格式导出。
  - `_process_engine_task()` — `mineru` / `ppocrv6` 流程，先把 Office/CAD 转成 PDF，再交给对应引擎。
- `priority == 1` 的任务（API Key 提交、且非管理员）完成后延迟 30 秒自动删除结果目录、上传目录和数据库记录；管理员 API 任务（priority=2）不清理。
- 单例 `task_engine` 在 `main.py` lifespan 中 `start()`/`stop()`。

### 文件处理流水线

```
上传（4MB 分片写盘）→ 校验扩展名/大小 → 建 tasks 记录 → 入队
├── 图片 → vl16: OCR；mineru/ppocrv6: 直接送引擎
├── PDF  → vl16: OCR；若 output_formats 含 "dwg" 则 PDF→DWG 纯转换
├── Office → LibreOffice → PDF → 引擎
│   └── 无 LO/失败：docx→python-docx、xlsx→openpyxl 文本提取（仅 vl16 路径）
└── CAD (dwg/dxf) → ACADxPDF → PDF+DXF → PDF 走引擎；vl16 路径额外提取 DXF 文字
    └── ACAD 失败 → bin/cad2x → 单页 PDF
```

扩展名分类集中在 `backend/utils/file_utils.py`（`IMAGE_EXTENSIONS` / `PDF_EXTENSIONS` / `CAD_EXTENSIONS` / `DOC_EXTENSIONS`）。

### 三引擎路由

任务级 `engine` 字段（前端下拉，默认 `mineru`；后端非法值也回落 `mineru`）：

| engine | 客户端 | 说明 |
|--------|--------|------|
| `mineru` | `services/mineru_client.py` | 异步三步：确保队列 running → `upload_with_progress` → 轮询 `/api/task/{id}` → 下载 ZIP 全量解压到结果目录。连续 10 次轮询 404 立即判定服务端任务丢失。原生进度映射到任务进度 10%~90%。 |
| `vl16` | `services/ocr_client.py` | 调 HPS `/layout-parsing`，`fileType=0`(PDF)/`1`(图片)，分片 base64。受 `high_precision` 影响。 |
| `ppocrv6` | `services/ocr_client.recognize_ppocrv6()` | 零幻觉文字行，结果坐标另存 `ppocrv6_data.json` 供前端文字层渲染。 |

`high_precision`（默认开启，任务级）**只对 `vl16` 生效**：`maxPixels` 从 `ocr_vlm_max_pixels`（~1.6MP）切到 `ocr_vlm_max_pixels_high`（~10MP），表格区域同步放大，耗时约 +50%。仅适用于 CAD 图纸、密集小字表格。

### PDF→DOCX 分流

- **非图片型 PDF**（有文本层）且 `output_formats` 含 `docx`：使用 exactdoc 直转（`backend/services/pdf_docx.py`），默认 `--refine 3`，保留原版式、图片、页眉页脚和活动页码。
- `output_formats == ["docx"]` 且 PDF 有文本层时走 `_process_pdf_docx` 快速路径，不调用 OCR 引擎；`result.md` 由 DOCX 文本提取，仅用于预览。混合格式请求仍用引擎生成 Markdown/JSON/TXT。
- **DOCX/DOC + 仅 `docx`/`markdown`**：走 `_process_office_direct` 快速路径，不调用 OCR。DOCX→Markdown 用 Pandoc（`backend/services/office_markdown.py`），DOC→DOCX 用 LibreOffice，DOC→Markdown 为 DOC→DOCX→Pandoc。图片内联为 data URI。
- 专用 API：`POST /api/v1/convert/markdown`（DOCX/DOC 同步；PDF 异步任务）、`POST /api/v1/convert/docx`（DOC/DOCX/ODT/RTF → DOCX）。
- **图片型 PDF**（无文本层）：仍走「引擎 OCR → Markdown → `ExportService.md_to_docx`」。
- exactdoc 失败/超时/超过 `pdf_docx_max_pages` 时自动回退 Markdown→DOCX；不影响任务完成。
- 配置：`PDF_DOCX_DIRECT_ENABLED` / `PDF_DOCX_REFINE_ROUNDS` / `PDF_DOCX_MAX_PAGES` / `PDF_DOCX_TIMEOUT` / `OFFICE_MARKDOWN_TIMEOUT`。
- Office 同步转换 API 最多 2 并发；DOCX→Markdown 图片内联限制单张 20MB、总量 50MB。

### 进度估算 (`backend/services/progress_estimator.py`)

- 用已完成任务的历史平均速度（bytes/sec）估算；样本不足 3 条时用粗略公式（约每 MB 20 秒）。
- 估算值封顶 95%，真正完成时才写 100%。
- Office/CAD 两阶段：0-45% 转换 PDF，50-95% OCR。`_progress_loop` 每 5 秒写库并推送 WebSocket。
- 非 VL 引擎不走估算循环，由引擎回调或阶段点主动 `_push_progress()`。

### 认证

- **Cookie 模式**：`/auth/login` → OOS `?from=<CALLBACK_URL>` → `/auth/callback?ticket=` → 调 OOS `/api/ticket/verify` → 同步 `users` 表 → 创建内存 session → 返回一段用 JS 写 cookie 的 HTML（避免重定向丢 Set-Cookie）。
- 管理员身份：`ADMIN_USERNAMES` 白名单（逗号分隔）在登录时强制设为管理员；白名单外不会自动降权，管理面板可手动改。
- **API Key 模式**：请求头 `X-API-Key: ak_...`。Key 以**明文**存 `api_keys.api_key`（内网场景，且有 `/auth/api-keys/{id}/reveal` 查看完整 Key 的接口）。
- `ocr_router._get_user_id_and_priority()` 统一返回 `(user_id, priority)`；`admin_router._require_admin()` 做管理员校验。
- WebSocket `/ws/progress?session_id=` **只支持 Cookie 会话**（session_id 从 cookie 取出后作为 query 传入）；API Key 客户端只能轮询 `GET /api/v1/tasks/{id}`。

### 数据库与迁移

- 模型：`users`、`tasks`、`api_keys`、`system_config`。
- `tasks` 关键字段：`priority` 0/1/2、`deleted` 0=正常/1=用户软删/2=管理员硬删、`merge_pdf`、`high_precision`、`engine`、`processing_time`。
- 启动时 `main.py::_auto_migrate()` 只对 `tasks` 表做增量补列（`ALTER TABLE`）；其他表结构变更不会自动迁移。`system_config` 表仅在 `init_db` 建表/插入默认值，运行时配置实际读 `.env`。
- `database.py` 对 openGauss 的版本字符串做了 `_get_server_version_info` 补丁，不要移除。

### 在线配置热生效

`backend/api/admin_settings_router.py` 的 `EDITABLE_SETTINGS` 是唯一白名单（超时、并发数、MinerU 参数、服务地址、数据库连接、会话时长等）：

1. 直接改 pydantic `Settings` 单例属性；
2. `_save_to_env()` 写回项目根 `.env`；
3. 若改了并发数，调用 `task_engine.refresh_semaphores()` 重建信号量（注意：重建后已持有旧信号量的任务不受影响）。

新增可在线配置项时，必须同时加到 `EDITABLE_SETTINGS`，前端管理面板才可见。

### 结果目录与导出

每个任务结果在 `data/results/<task_id>/`，常见文件：

- `result.md`（前端展示/下载的主结果）
- `result.raw.json`（原始响应）；`result_json` 读取优先级：`result.raw.json` → MinerU 的 `*_content_list.json` → `result.json`
- `result.json` / `result.txt` / `result.docx`（按 `output_formats` 生成）
- `source_<原文件名>`（源文件副本）、`images/`（OCR 提取图片）、`ppocrv6_data.json`
- Office/CAD 转换出的 PDF（仅 vl16 路径保留）；CAD 额外保留 DXF 和 `<base>_dxf.md`

`ExportService` 负责 md→txt/docx；docx 导出前会把 `$...$` LaTeX 转成 Unicode 符号（python-docx 不渲染 LaTeX）。

### 版本与更新日志

- 版本号唯一来源是根目录 `CHANGELOG.md` 中**第一个** `## [x.y.z]` 条目。
- `GET /api/version` 返回 `{ui_version, engine_version}`（引擎版本硬编码在 `main.py`）。
- `GET /api/changelog` 返回原文，前端顶栏点击弹出渲染。
- **改用户可见功能后先更新 `CHANGELOG.md`**，否则顶栏版本号不变。

## API 路由

| 路由 | 说明 |
|------|------|
| `POST/GET /api/v1/tasks` | 提交 / 列出任务（表单字段含 `engine`、`high_precision`、`merge_pdf`、`output_formats`） |
| `GET/DELETE /api/v1/tasks/{id}` | 详情（含 `result`、`result_json`、`ppocr_data`）/ 取消 |
| `GET /api/v1/files` | 文件管理分页列表 |
| `GET /api/v1/files/{id}/preview` | 原文件预览（图片/PDF） |
| `GET /api/v1/files/{id}/download?format=` | zip（默认；`md` 同样返回整目录 zip）/ txt / json / docx |
| `POST /api/v1/files/batch-download` | 批量打包结果目录 |
| `DELETE /api/v1/files/{id}` | 管理员硬删（删文件 + `deleted=2`）/ 用户软删 |
| `/auth/*` | SSO 登录、回调、登出、`/auth/me`、API Key CRUD |
| `/api/v1/admin/*` | 用户管理、在线设置、`test-connection`、`clear-tasks`、`logs` |
| `POST /api/v1/convert/markdown` | DOCX/DOC 同步转 Markdown；PDF 创建异步任务 |
| `POST /api/v1/convert/docx` | DOC/DOCX/ODT/RTF 转 DOCX，直接返回文件 |
| `/ws/progress` | WebSocket 进度推送 |
| `GET /health`、`/api/version`、`/api/changelog` | 健康检查与版本信息 |

静态文件挂载在最后，因此新增 API 路由必须在 `app.mount("/")` 之前注册。

## 前端

- 入口 `frontend/src/main.js`：Pinia + Router + Element Plus，注册了全局 axios 401 拦截（跳 `/auth/login`）。
- 路由只有 `/login` 和 `/`；`/` 由 `MainView.vue` 用 `activeTab` 切换三个子视图：`TaskWorkspace`（上传 + 任务队列）、`FileManagement`、`AdminPanel`。
- 路由守卫检查 `document.cookie` 里是否有 `paddleocr_session`。
- Pinia stores：`upload`（待上传文件、outputFormats、engine、highPrecision、mergePdf）、`task`（任务列表与选中结果）、`file`（文件管理分页）、`user`。
- 预览组件分工：`FilePreview.vue` 只负责源文件（图片/PDF iframe）；`MarkdownPreview.vue` 渲染识别结果，并在 `ppocrData` 存在时挂载 `PPOCRPreview.vue`（PP-OCRv6 文字层）。
- 任务状态排序权重在 `stores/task.js::STATUS_ORDER`（processing > queued > pending > completed > failed > cancelled）。

## 关键外部依赖

| 服务 | 配置项 | 默认地址 |
|------|--------|----------|
| PaddleOCR-VL HPS | `OCR_SERVICE_URL` | `http://localhost:5564` |
| ACADxPDF（DWG↔PDF/DXF） | `ACAD_SERVICE_URL` / `ACAD_SERVICE_APIKEY` | `http://192.168.0.5:5557` |
| PP-OCRv6 | `PPOCRV6_SERVICE_URL` | `http://192.168.0.71:5561` |
| MinerU | `MINERU_SERVICE_URL` | `http://192.168.0.71:5555` |
| OOS SSO | `YZ_LOGIN_URL` | `http://localhost:5551` |

## 注意事项

- 配置文件从 `.env.example` 复制；`.env` 含密码，不要提交。
- `SECRET_KEY` 用于 session token 加密，生产环境务必更换。
- LibreOffice 并发转换使用独立 `UserInstallation` profile 避免锁冲突；超时由 `libreoffice_timeout` 控制。
- Docker 镜像已内置 `fonts-wqy-microhei`，并 COPY `.fonts/` 下的工程字体；`.fonts/` 不入 git。**构建镜像时 `.fonts/` 目录必须存在**，否则 `COPY .fonts/` 会直接失败。
- 容器时区通过 `TZ=Asia/Shanghai` + 挂载 `/etc/localtime` 固定，日志与任务时间才与宿主机一致。
- 日志写 `data/logs/app.log`（10MB × 5 轮转），管理面板 `/api/v1/admin/logs` 只 tail 最近 N 行。
- 端口 5553（后端）/ 3000（前端 dev）；`bin/cad2x` 是 3.5MB 第三方二进制，被 gitignore。
- 数据库连接参数修改后需要重启进程——SQLAlchemy engine 在模块导入时创建，热更新只改 `.env` 不重建连接池。
- 开发机构建 Docker 镜像时必须传 `--secret id=tproxy_ca,src=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem`（TLS 代理根 CA），否则 pip 安装会 SSL 校验失败。
- 外部服务接口细节见 `docs/`：`PP-OCRv6部署与API说明.md`、`ACADxPDF API说明文档.md`、`API.md`；早期设计与压测记录在 `docs/superpowers/`。
