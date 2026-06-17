# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 快速命令

```bash
# 后端启动
pip install -r requirements.txt
python -m backend.init_db       # 初始化数据库
python -m backend.main           # 开发模式（热重载）
uvicorn backend.main:app --host 0.0.0.0 --port 5553  # 生产模式

# 前端启动
cd frontend && npm install && npm run dev    # 开发服务器（端口3000，代理到5553）
cd frontend && npm run build                 # 生产构建到 ../static/

# Docker 部署
cd docker && docker compose up -d --build
docker build -t paddleocr-ui -f docker/Dockerfile .

# 一键启动
bash start.sh
```

## 技术栈

| 层 | 技术 |
|---|------|
| 后端框架 | FastAPI (Python 3.12+) — `backend/main.py` |
| 数据库 | PostgreSQL / openGauss-lite，SQLAlchemy 2.0 async + asyncpg |
| 前端 | Vue 3 + Element Plus + Pinia + Vite — `frontend/` |
| OCR 引擎 | PaddleOCR-VL HPS 产线服务（外部，端口 5564） |
| CAD 转换 | ACADxPDF 服务（外部，端口 5557）→ DWG→PDF+DXF；本地 cad2x 回退 |
| DXF 文字提取 | ezdxf 库直接提取文字实体 |
| 文档转换 | LibreOffice headless → PDF；无 LO 时 docx/xlsx 降级 Python 提取 |
| 登录 | OOS SSO（Cookie session + API Key 两种认证） |
| 实时推送 | WebSocket 进度推送 + HTTP 轮询降级 |

## 架构核心

### 任务引擎 (`backend/services/task_engine.py`)

基于 `asyncio.PriorityQueue` 的 3 级优先级队列。优先级：管理员(2) > API(1) > 普通用户(0)，数字越大越优先。三个独立的 `asyncio.Semaphore` 控制并发：
- `image_semaphore` — 图片类任务
- `pdf_semaphore` — PDF 类任务
- `acad_semaphore` — CAD 图纸任务

单例 `task_engine` 在 `backend/main.py` 的 lifespan 中启动，shutdown 时自动恢复未完成任务入队。

### 文件处理流水线

```
上传 → 文件分类 → 任务引擎入队 → _process_task()
├── 图片 (jpg/png/bmp/tiff/webp) → OCR 直接识别
├── PDF → OCR 直接识别（或 PDF→DWG 纯转换）
├── Office (doc/xls/ppt...) → LibreOffice → PDF → OCR
│   └── 降级: docx → python-docx, xlsx → openpyxl 文本提取
├── CAD (dwg/dxf) → ACADxPDF → PDF + DXF → OCR + DXF 文字提取
│   └── 回退: cad2x → PDF → OCR
```

文件扩展名分类定义在 `backend/utils/file_utils.py`。

### OCR 客户端 (`backend/services/ocr_client.py`)

调用 HPS `/layout-parsing` 接口，参数包括 `useLayoutDetection`, `mergeTables`, `relevelTitles` 等。PDF 参数 `fileType=0`，图片 `fileType=1`。分片 base64 编码流式传输大文件。返回 `{markdown, pages, structured, images}` 结构化结果，解析逻辑在 `_parse_response()` 中。

**高精度模式** (`high_precision`)：任务级开关，前端默认开启。开启时 `maxPixels` 从 1.6MP 提升至 ~10MP（`ocr_vlm_max_pixels_high` / `ocr_vlm_table_max_pixels_high`），适用于 AutoCAD 图纸、密集小字表格（A1 图纸 8pt 字在 1.6MP 下仅 5px 不可读）。耗时约 +50%。链路：前端开关 → `ocr_router.create_task(high_precision)` → `Task.high_precision` → `task_engine` 传给 `ocr_client.recognize_pdf/image(high_precision=)` → 切换 `maxPixels`。仅对 VL-1.6 引擎生效。

**引擎选择** (`engine`)：任务级开关，前端引擎下拉，默认 `vl16`。三引擎路由：
- `vl16`（PaddleOCR-VL-1.6，默认）→ `ocr_client` 现有流程，受 `high_precision` 影响
- `ppocrv6`（PP-OCRv6）→ `ocr_client.recognize_ppocrv6()`，POST `ppocrv6_service_url`(0.71:5561)/ocr，零幻觉文字行
- `mineru`（MinerU）→ `mineru_client.process_mineru()`，ACADxPDF 式异步三步（队列保障→提交→轮询 path→下载 query ZIP→解压全保留），服务 `mineru_service_url`(0.71:5555)

非 VL 引擎在 `task_engine._process_engine_task` 独立处理（Office/CAD 先转 PDF），不走 VL 流程。MinerU 结果（md/layout.pdf/origin.pdf/json/images）全量解压到 `result_path`。

### 进度估算 (`backend/services/progress_estimator.py`)

基于历史任务的平均处理速度 (bytes/sec) 估算当前进度，数据不足时用粗略公式（PDF 约每 MB 20 秒）。估算值上限 95%，仅在真正完成时变为 100%。Office/CAD 文档分两阶段：0-50% 转换 PDF，50-100% OCR。

### API 路由结构

| 路由 | 文件 | 说明 |
|------|------|------|
| `/auth/*` | `backend/api/auth_router.py` | SSO 登录/回调/登出/API Key CRUD |
| `/api/v1/tasks/*` | `backend/api/ocr_router.py` | OCR 任务提交/查询/取消 |
| `/api/v1/files/*` | `backend/api/file_router.py` | 文件列表/预览/下载/批量下载 |
| `/api/v1/admin/*` | `backend/api/admin_router.py` | 用户管理 |
| `/api/v1/admin/*` | `backend/api/admin_settings_router.py` | 在线配置（热生效） |
| `/api/v1/admin/*` | `backend/api/admin_log_router.py` | 日志查看 |
| `/ws/progress` | `backend/api/ws_router.py` | WebSocket 进度推送 |

### 认证流程

**Cookie 模式**: 用户访问 `/` → 检测无 session → 跳转 `/auth/login` → OOS SSO → `/auth/callback?ticket=xxx` → 验证 ticket → 写入本地 users 表 → 创建 session → 设置 cookie。

**API Key 模式**: 请求头 `X-API-Key: ak_xxxxxxx` 直接认证。

`_get_user_id_and_priority()` 在 `backend/api/ocr_router.py` 中统一处理两种方式，返回 `(user_id, priority)`。

### 数据库模型

- `users` — 用户表（username, display_name, is_admin, created_at）
- `tasks` — 任务表（含 priority 0/1/2，deleted 0/1/2，merge_pdf 标志）
- `api_keys` — API Key 表（前缀 ak_，SHA256 hash 存储）
- `system_config` — 系统配置表

自动迁移在 `_auto_migrate()` 中实现，启动时检测新增列并执行 `ALTER TABLE`。

### 在线配置热生效

管理面板 (`admin_settings_router.py`) 修改配置后：
1. 直接更新 pydantic `Settings` 实例属性
2. 持久化到 `.env` 文件
3. 若修改了并发数，调用 `task_engine.refresh_semaphores()` 即时生效，无需重启

### 前端路由与组件

- `/login` → `LoginView.vue` — SSO 登录页
- `/` → `MainView.vue` — 主布局（顶部导航 + 子路由）
  - `TaskWorkspace.vue` — 上传 + 任务队列
  - `FileManagement.vue` — 文件管理列表
  - `AdminPanel.vue` — 管理面板
- 路由守卫：非 login 页无 `paddleocr_session` cookie 时跳转登录
- 全局 axios 拦截器：401 响应自动跳转 `/auth/login`

### 关键外部依赖地址

- OCR 服务: `OCR_SERVICE_URL`（默认 `http://localhost:5564`）
- ACADxPDF 服务: `ACAD_SERVICE_URL`（默认 `http://192.168.0.5:5557`）
- SSO 登录: `YZ_LOGIN_URL`（默认 `http://localhost:5551`）

### API 任务的自动清理

`priority=1`（API 用户提交）的任务完成后延迟 30 秒自动清理输入文件和数据库记录，前端用户任务（priority=0）和管���员任务（priority=2）保留不清理。

## 注意事项

- 配置文件 `.env` 从 `.env.example` 复制，不要提交 `.env` 到 git
- `SECRET_KEY` 用于 session token 加密，生产环境务必更换
- LibreOffice 多实例并发时用独立 `UserInstallation` profile 避免锁冲突
- openGauss-lite 数据库需要 `database.py` 中的版本解析 patch
- 项目监听端口 5553，前端开发端口 3000（通过 Vite proxy 转发）
- `bin/cad2x` 是第三方二进制（3.5MB），被 `.gitignore` 排除
