# PaddleOCR Web UI / PaddleOCR Web Interface

基于 PaddleOCR 的 Web 文档识别服务，支持 22 种文件格式，提供可视化界面和 REST API。
A web document OCR service based on PaddleOCR, supporting 22 file formats with a visual interface and REST API.

---

## 功能特性 / Features

- **22 种格式支持 / 22 Format Support**：PDF、图片（6种）、Office 文档（15种）
  PDF, images (6 types), Office documents (15 types)
- **多格式输出 / Multi-format Output**：Markdown、JSON（结构化）、纯文本、DOCX、ZIP 打包
  Markdown, structured JSON, plain text, DOCX, ZIP package
- **图片提取 / Image Extraction**：OCR 识别结果中的图片自动提取保存
  Images from OCR results are automatically extracted and saved
- **Office 文档转换 / Office Conversion**：LibreOffice headless 转 PDF 后识别，支持 doc/docx/xls/xlsx/ppt/pptx 等
  Office docs converted via LibreOffice headless before OCR
- **任务队列 / Task Queue**：3 级优先级队列，可配置并发数
  3-level priority queue with configurable concurrency
- **实时进度 / Real-time Progress**：WebSocket 推送 + HTTP 轮询降级
  WebSocket push with HTTP polling fallback
- **管理后台 / Admin Panel**：用户管理、API Key 管理、系统设置、日志查看
  User management, API Key management, system settings, log viewer
- **SSO 登录 / SSO Login**：支持 OOS 统一登录
  Supports OOS unified login
- **Docker 部署 / Docker Deployment**：一键构建部署
  One-click build and deploy

---

## 快速开始 / Quick Start

### Docker 部署（推荐 / Recommended）

```bash
docker build -t paddleocr-ui .
docker run -d -p 5553:5553 \
  -v ./data:/app/data \
  -e DB_HOST=your-db-host \
  -e DB_PASSWORD=your-password \
  paddleocr-ui
```

### 手动部署 / Manual Deploy

**依赖 / Dependencies:**
- Python 3.12+
- PostgreSQL（或 openGauss-lite）
- LibreOffice（可选，Office 格式转换需要 / Optional, needed for Office formats）
- Node.js 18+（前端构建 / Frontend build）

```bash
# 安装后端依赖 / Install backend dependencies
pip install -r requirements.txt

# 构建前端 / Build frontend
cd frontend && npm install && npm run build && cp -r dist/* ../static/

# 配置 / Configuration
cp .env.example .env
# 编辑 .env 填入实际配置 / Edit .env with your settings

# 初始化数据库 / Initialize database
python -m backend.init_db

# 启动 / Start
python -m backend.main
```

访问 http://localhost:5553 即可使用。
Visit http://localhost:5553 to use.

---

## 支持格式 / Supported Formats

### 直接 OCR 识别 / Direct OCR

| 格式 / Format | 说明 / Description |
|--------|---------|
| pdf | PDF 文档 / PDF documents |
| jpg / jpeg | JPEG 图片 / JPEG images |
| png | PNG 图片 / PNG images |
| bmp | BMP 图片 / BMP images |
| tiff / tif | TIFF 图片 / TIFF images |
| webp | WebP 图片 / WebP images |

### LibreOffice 转换后识别 / Via LibreOffice Conversion

| 格式 / Format | 说明 / Description |
|--------|---------|
| doc / docx | Word 文档 / Word documents |
| xls / xlsx | Excel 表格 / Excel spreadsheets |
| ppt / pptx | PowerPoint 演示文稿 / PowerPoint presentations |
| odt / ods / odp | OpenDocument 格式 / OpenDocument formats |
| rtf / csv / txt / html | 其他文档 / Other documents |

---

## API 使用 / API Usage

### 认证 / Authentication

所有 API 请求需携带 API Key / All API requests require an API Key:

```
X-API-Key: ak_xxxxxxxxxxxxx
```

### 提交任务 / Submit Task

```bash
curl -X POST http://localhost:5553/api/v1/tasks \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@document.pdf" \
  -F "task_type=ocr" \
  -F 'output_formats=["markdown","json"]'
```

### 查询状态 / Query Status

```bash
curl http://localhost:5553/api/v1/tasks/98 -H "X-API-Key: YOUR_KEY"
```

### 下载结果 / Download Result

```bash
# ZIP 打包（含源文件+图片+结果）/ ZIP package (source + images + results)
curl -O http://localhost:5553/api/v1/files/98/download?format=zip \
  -H "X-API-Key: YOUR_KEY"

# 其他格式 / Other formats: md, json, txt, docx
curl -O http://localhost:5553/api/v1/files/98/download?format=json \
  -H "X-API-Key: YOUR_KEY"
```

详细 API 文档见 [docs/API.md](docs/API.md)，使用说明见 [docs/使用说明.md](docs/使用说明.md)。
For detailed API docs, see [docs/API.md](docs/API.md).

---

## 系统架构 / Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   Vue 3     │────▶│   FastAPI    │────▶│  PaddleOCR  │
│  前端界面    │◀────│   后端服务    │◀────│  HPS 产线    │
└─────────────┘     └──────┬───────┘     └─────────────┘
                    ┌──────┴───────┐
                    │  PostgreSQL  │
                    │  (openGauss) │
                    └──────────────┘
```

- **前端 / Frontend**: Vue 3 + Element Plus + Pinia
- **后端 / Backend**: FastAPI + SQLAlchemy async + WebSocket
- **OCR 引擎 / OCR Engine**: PaddleOCR HPS 产线服务 / PaddleOCR HPS pipeline service
- **文档转换 / Doc Conversion**: LibreOffice headless
- **任务队列 / Task Queue**: asyncio.PriorityQueue（3 级优先级 / 3-level priority）

---

## 管理后台 / Admin Panel

管理后台包含以下模块 / The admin panel includes:

| 模块 / Module | 功能 / Function |
|--------|---------|
| 用户管理 / User Management | 查看用户、设置管理员权限 / View users, set admin rights |
| API Key 管理 / API Key Management | 创建、吊销、查看 Key / Create, revoke, view keys |
| 系统设置 / System Settings | 超时配置、并发数（在线修改立即生效）/ Timeouts, concurrency (hot-reload) |
| 系统日志 / System Logs | 实时查看运行日志 / Real-time log viewer |

---

## 配置项 / Configuration

所有配置通过 `.env` 文件或环境变量设置，详见 [.env.example](.env.example)。

All settings via `.env` file or environment variables, see [.env.example](.env.example).

---

## 许可证 / License

MIT
