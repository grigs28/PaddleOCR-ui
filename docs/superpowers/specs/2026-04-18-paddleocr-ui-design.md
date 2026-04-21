# PaddleOCR Web UI 设计文档

**日期**: 2026-04-18
**状态**: 已确认
**仓库**: https://github.com/grigs28/PaddleOCR-ui.git

---

## 1. 项目概述

基于 PaddleOCR-VL-1.5-0.9B 模型构建的 Web OCR 服务，支持多用户并发、异步队列处理、实时进度推送，同时提供 Web UI 和 REST API 两种使用方式。

## 2. 整体架构

```
┌──────────────────────────────────────────────────────┐
│                    Vue 3 前端                         │
│  登录页 | 上传页 | 任务列表 | 管理后台 | API 文档      │
└──────────────────┬───────────────────────────────────┘
                   │ HTTP / WebSocket
┌──────────────────▼───────────────────────────────────┐
│                  FastAPI 后端                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐              │
│  │ 认证模块  │ │ 文件模块  │ │ 任务模块  │              │
│  │(yz-login)│ │(上传/下载)│ │(队列/OCR)│              │
│  └──────────┘ └──────────┘ └────┬─────┘              │
│                                  │                    │
│  ┌──────────────────────────────▼──────────────┐     │
│  │     异步任务引擎                              │     │
│  │  asyncio.Semaphore(3) 控制并发               │     │
│  │  内存队列 + openGauss 状态持久化              │     │
│  └─────────────────────────────────────────────┘     │
│                                  │                    │
│  ┌───────────────┐  ┌───────────▼──────────────┐     │
│  │  REST API 模块 │  │   PaddleOCR-VL 客户端     │     │
│  │  (API Key 认证)│  │  (OpenAI 兼容 API)        │     │
│  └───────────────┘  └──────────────────────────┘     │
└──────────────────┬──────────────┬────────────────────┘
                   │              │
          ┌────────▼──┐   ┌──────▼──────────┐
          │ openGauss  │   │ PaddleOCR-VL    │
          │ 192.168.   │   │ 192.168.0.70    │
          │ 0.98:5432  │   │ :5564           │
          └────────────┘   └─────────────────┘
```

**架构风格**: 方案 C — 轻量级内存队列 + openGauss 持久化，无 Redis/Celery 依赖。

## 3. 技术选型

| 组件 | 技术 | 版本/说明 |
|------|------|-----------|
| 后端框架 | FastAPI | 异步，原生支持 WebSocket |
| 前端框架 | Vue 3 + Vite | 组件化开发 |
| 数据库 | openGauss-lite | 7.0.0-RC1, 192.168.0.98:5432 |
| ORM | SQLAlchemy (async) + asyncpg | openGauss 兼容 PostgreSQL 协议 |
| OCR 引擎 | PaddleOCR-VL-1.5-0.9B | 通过 OpenAI 兼容 API 调用 |
| 格式转换 | pandoc | Markdown → DOCX/TXT |
| PDF 处理 | PyMuPDF (fitz) | PDF 转图片 |
| Word/Excel 读取 | python-docx / openpyxl | 提取图片/表格 |
| 状态管理 | Pinia | Vue 3 状态管理 |
| 实时通信 | WebSocket | FastAPI 原生支持 |
| 部署 | Docker + 裸机双模式 | Dockerfile + systemd/supervisor |

## 4. 数据库设计

**数据库连接**:
- 地址: 192.168.0.98:5432
- 用户名: grigs
- 密码: Slnwg123$
- 版本: openGauss-lite 7.0.0-RC1
- **要求**: 必须使用 openGauss 原生指令，严禁 PostgreSQL 兼容语句

### 4.1 用户表

```sql
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    is_admin SMALLINT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

用户信息从 yz-login (http://192.168.0.19:5555) 同步，首次登录时自动创建本地记录。

### 4.2 任务表

```sql
CREATE TABLE tasks (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    status VARCHAR(20) DEFAULT 'pending',
    task_type VARCHAR(20),
    input_filename VARCHAR(500),
    input_file_path VARCHAR(1000),
    input_file_size BIGINT,
    output_formats VARCHAR(100),
    result_path VARCHAR(1000),
    error_message TEXT,
    progress SMALLINT DEFAULT 0,
    page_current INTEGER DEFAULT 0,
    page_total INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);
```

**状态流转**: pending → queued → processing → completed / failed / cancelled

**task_type 取值**: ocr / table / formula / chart

**output_formats**: JSON 数组字符串，如 `["markdown","json","txt","docx"]`

### 4.3 API Key 表

```sql
CREATE TABLE api_keys (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    api_key VARCHAR(64) UNIQUE NOT NULL,
    name VARCHAR(100),
    is_active SMALLINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMP
);
```

### 4.4 系统配置表

```sql
CREATE TABLE system_config (
    config_key VARCHAR(100) PRIMARY KEY,
    config_value TEXT,
    description VARCHAR(500),
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

预设配置项:
- `max_concurrency`: 最大并发数（默认 3）
- `max_file_size_mb`: 最大文件大小 MB（默认 100）
- `allowed_file_types`: 允许的文件类型
- `queue_paused`: 队列是否暂停（0/1）

## 5. 后端模块设计

```
backend/
├── main.py                 # FastAPI 入口，路由注册，生命周期管理
├── config.py               # 配置管理（环境变量/配置文件）
├── database.py             # openGauss 连接池
├── auth/
│   ├── yz_login.py         # yz-login Ticket 认证集成
│   ├── session.py          # 本地 Session 管理（Cookie）
│   └── api_key.py          # REST API Key 认证
├── models/
│   ├── user.py             # 用户 ORM 模型
│   ├── task.py             # 任务 ORM 模型
│   ├── api_key.py          # API Key ORM 模型
│   └── system_config.py    # 系统配置 ORM 模型
├── api/
│   ├── auth_router.py      # 登录/登出接口
│   ├── task_router.py      # 任务 CRUD（Web UI 用）
│   ├── file_router.py      # 文件上传/下载
│   ├── admin_router.py     # 管理员接口
│   └── public_api.py       # REST API（外部调用）
├── services/
│   ├── task_engine.py      # 异步任务引擎
│   ├── ocr_client.py       # PaddleOCR-VL 客户端
│   ├── file_converter.py   # 格式转换
│   ├── file_preprocessor.py # 文件预处理（PDF/Word/Excel → 图片）
│   └── progress.py         # 进度管理 + WebSocket 推送
├── ws/
│   └── progress_ws.py      # WebSocket 端点
└── utils/
    ├── file_utils.py       # 文件处理工具
    └── pdf_utils.py        # PDF 转图片
```

### 5.1 任务引擎 (task_engine.py)

核心逻辑:

```python
class TaskEngine:
    def __init__(self, max_concurrency=3):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.queue = asyncio.Queue()
        self.active_tasks = {}  # task_id → asyncio.Task
        self.ws_manager = WebSocketManager()

    async def submit(self, task_id: str):
        """提交任务到队列"""
        await self.queue.put(task_id)
        # 更新 DB 状态为 queued

    async def worker(self):
        """工作循环，从队列取任务执行"""
        while True:
            task_id = await self.queue.get()
            async with self.semaphore:
                await self._process(task_id)

    async def _process(self, task_id: str):
        """处理单个任务"""
        # 1. 更新状态为 processing
        # 2. 预处理文件（PDF/Word/Excel → 图片列表）
        # 3. 逐页调用 PaddleOCR-VL API
        # 4. 合并结果，转换输出格式
        # 5. 更新状态为 completed/failed
        # 6. WebSocket 推送完成通知

    async def recover(self):
        """服务重启时从 openGauss 恢复未完成任务"""
        # 查询 status IN ('pending', 'queued', 'processing') 的任务
        # 重新提交到队列
```

### 5.2 OCR 客户端 (ocr_client.py)

```python
class PaddleOCRVLClient:
    def __init__(self):
        self.base_url = "http://192.168.0.70:5564/v1"
        self.model = "PaddleOCR-VL-1.5-0.9B"

    TASKS = {
        "ocr": "OCR:",
        "table": "Table Recognition:",
        "formula": "Formula Recognition:",
        "chart": "Chart Recognition:",
    }

    async def recognize(self, image: str, task_type: str) -> str:
        """调用 PaddleOCR-VL API"""
        # OpenAI 兼容格式请求
        # 支持图片 URL 或 base64 输入

    async def process_file(self, file_path: str, task_type: str, progress_cb=None) -> dict:
        """处理整个文件（PDF 多页等）"""
        # 1. 预处理为图片列表
        # 2. 逐页调用 recognize
        # 3. 合并结果
```

### 5.3 认证流程

**Web UI 认证 (yz-login Ticket)**:
1. 用户访问 `/login` → 跳转 `http://192.168.0.19:5555/login?from=回调地址`
2. yz-login 登录成功 → 回调 `?ticket=xxx`
3. 后端调用 `http://192.168.0.19:5555/api/ticket/verify?ticket=xxx` 验证
4. 验证通过 → 创建本地 Session，同步/更新用户信息到 openGauss

**REST API 认证 (API Key)**:
1. 用户在 Web UI 生成 API Key（管理页面）
2. 请求头携带 `X-API-Key: <api_key>`
3. 后端验证 API Key → 获取关联用户 → 执行操作

### 5.4 文件预处理流程

```
输入文件类型判断
├── 图片 (jpg/png/bmp/tiff) → 直接使用
├── PDF → PyMuPDF 逐页渲染为图片
├── Word (.docx) → python-docx 提取图片 + 文字
└── Excel (.xlsx) → openpyxl 提取为图片/表格截图
```

### 5.5 格式转换流程

```
PaddleOCR-VL 原始输出
├── Markdown (.md)  → 直接保存
├── JSON (.json)    → 直接保存
├── HTML (.html)    → 表格识别结果直接保存
├── XLSX (.xlsx)    → 表格识别结果直接保存
├── TXT (.txt)      ← Markdown 去标记转换
└── DOCX (.docx)    ← pandoc Markdown → DOCX 转换
```

## 6. 前端设计

### 6.1 页面结构

```
frontend/  (Vue 3 + Vite)
├── src/
│   ├── views/
│   │   ├── LoginView.vue          # 登录页（跳转 yz-login）
│   │   ├── DashboardView.vue      # 主面板（上传 + 任务列表）
│   │   ├── TaskDetailView.vue     # 任务详情（预览 + 下载）
│   │   ├── AdminView.vue          # 管理后台
│   │   └── ApiDocsView.vue        # API 文档页
│   ├── components/
│   │   ├── FileUploader.vue       # 多文件拖拽上传
│   │   ├── TaskList.vue           # 任务列表（筛选/排序/分页）
│   │   ├── TaskCard.vue           # 任务卡片（状态/进度/操作）
│   │   ├── ResultPreview.vue      # 结果预览（Markdown/JSON 渲染）
│   │   ├── FormatSelector.vue     # 输出格式多选器
│   │   └── ProgressBar.vue        # 实时进度条（WebSocket 驱动）
│   ├── composables/
│   │   ├── useWebSocket.js        # WebSocket 连接管理（自动重连）
│   │   ├── useAuth.js             # 认证状态管理
│   │   └── useApi.js              # API 请求封装
│   └── stores/
│       └── user.js                # Pinia 用户状态
```

### 6.2 用户交互流程

**普通用户流程**:
1. 访问系统 → 自动跳转 yz-login 登录
2. 进入 Dashboard → 拖拽上传文件（支持多文件）
3. 选择任务类型（OCR/表格/公式/图表）和输出格式（多选）
4. 提交 → 任务进入队列 → WebSocket 实时显示进度
5. 完成后预览结果 → 选择格式下载
6. 管理自己的任务（查看/删除/重新提交）

**管理员额外功能**:
- 查看所有用户的任务
- 暂停/恢复队列
- 清空队列
- 调整系统参数（并发数、文件大小限制等）
- 管理用户（查看/禁用）

## 7. REST API 设计

外部系统通过 API Key 调用，共享同一套任务引擎。

### 7.1 端点列表

```
POST   /api/v1/ocr                 # 提交 OCR 任务
GET    /api/v1/tasks                # 列出当前用户的任务
GET    /api/v1/tasks/{id}           # 查询任务状态和详情
GET    /api/v1/tasks/{id}/result    # 下载结果文件
DELETE /api/v1/tasks/{id}           # 删除任务
GET    /api/v1/formats              # 查询支持的输出格式
GET    /api/v1/task-types           # 查询支持的任务类型
```

### 7.2 提交任务请求示例

```json
POST /api/v1/ocr
Headers: X-API-Key: ak_xxxxx

{
    "file": "<multipart upload>",
    "task_type": "ocr",
    "output_formats": ["markdown", "json", "txt"]
}
```

### 7.3 响应示例

```json
{
    "task_id": "12345",
    "status": "queued",
    "task_type": "ocr",
    "output_formats": ["markdown", "json", "txt"],
    "created_at": "2026-04-18T10:00:00Z",
    "poll_url": "/api/v1/tasks/12345"
}
```

## 8. WebSocket 协议

连接地址: `ws://<host>/ws/progress?token=<session_token>`

### 8.1 服务端推送消息

```json
// 进度更新
{
    "type": "progress",
    "task_id": "12345",
    "progress": 65,
    "status": "processing",
    "message": "正在处理第 3/5 页..."
}

// 任务完成
{
    "type": "completed",
    "task_id": "12345",
    "result": {
        "formats": ["markdown", "json", "txt"],
        "download_urls": {
            "markdown": "/api/v1/tasks/12345/result?format=markdown",
            "json": "/api/v1/tasks/12345/result?format=json",
            "txt": "/api/v1/tasks/12345/result?format=txt"
        }
    }
}

// 任务失败
{
    "type": "failed",
    "task_id": "12345",
    "error": "OCR 处理超时"
}

// 队列状态变化（管理员）
{
    "type": "queue_status",
    "paused": false,
    "pending_count": 5,
    "processing_count": 3
}
```

## 9. 部署设计

### 9.1 Docker 部署

```yaml
# docker-compose.yml
services:
  paddleocr-ui:
    build: .
    ports:
      - "8080:8080"
    environment:
      - DB_HOST=192.168.0.98
      - DB_PORT=5432
      - DB_USER=grigs
      - DB_PASSWORD=Slnwg123$
      - DB_NAME=paddleocr_ui
      - OCR_SERVICE_URL=http://192.168.0.70:5564/v1
      - OCR_MODEL_NAME=PaddleOCR-VL-1.5-0.9B
      - YZ_LOGIN_URL=http://192.168.0.19:5555
    volumes:
      - ./data/uploads:/app/uploads
      - ./data/results:/app/results
    restart: unless-stopped
```

### 9.2 裸机部署

```bash
# 启动
python backend/main.py --host 0.0.0.0 --port 8080

# 或使用 systemd service
```

## 10. 文件存储结构

```
data/
├── uploads/              # 上传的原始文件
│   └── {task_id}/
│       └── original.ext
├── results/              # OCR 结果文件
│   └── {task_id}/
│       ├── result.json
│       ├── result.md
│       ├── result.txt
│       ├── result.docx
│       ├── result.xlsx
│       └── pages/        # 每页的中间结果
│           ├── page_001.json
│           ├── page_001.png
│           └── ...
└── temp/                 # 临时文件（定期清理）
```

## 11. 安全设计

1. **认证**: yz-login Ticket + API Key 双模式
2. **文件类型校验**: 后端验证文件扩展名和 MIME 类型
3. **文件大小限制**: 可配置，默认 100MB
4. **路径安全**: 文件路径不可预测（使用 task_id 隔离）
5. **SQL 注入防护**: 使用 ORM 参数化查询
6. **API Key**: 64 字符随机字符串，支持吊销

## 12. 错误处理

1. **OCR 服务不可用**: 任务标记为 failed，错误信息记录到 DB，WebSocket 通知用户
2. **数据库连接断开**: 自动重连，任务状态从 DB 恢复
3. **WebSocket 断开**: 前端自动重连，重连后同步最新状态
4. **文件转换失败**: 记录错误，部分成功的格式仍可下载
5. **服务重启**: 从 openGauss 恢复 pending/queued 任务重新入队

## 13. 外部依赖

| 服务 | 地址 | 用途 |
|------|------|------|
| PaddleOCR-VL | 192.168.0.70:5564 | OCR 推理 |
| openGauss | 192.168.0.98:5432 | 数据存储 |
| yz-login | 192.168.0.19:5555 | 用户认证 |
| GitHub | grigs28/PaddleOCR-ui | 代码仓库 |
