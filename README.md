[简体中文](README.md) | [English](README.en.md)

# PaddleOCR Web UI

基于 PaddleOCR 的 Web 文档识别服务，支持 22 种文件格式，提供可视化界面和 REST API。

---

## 功能特性

**文件处理**
- **22 种格式支持**：PDF、图片（jpg/png/bmp/tiff/webp）、Office 文档（doc/docx/xls/xlsx/ppt/pptx/odt/ods/odp/rtf/csv/txt/html 等）
- **Office 文档转换**：LibreOffice headless 转 PDF 后识别，无 LibreOffice 时 docx/xlsx 自动降级为 Python 文本提取
- **图片提取**：OCR 识别结果中的图片自动提取保存到 images/ 目录，Markdown 中生成相对路径引用
- **多格式输出**：Markdown、JSON（按页按块结构化）、纯文本、DOCX、ZIP 打包下载
- **源文件保留**：结果目录保留源文件副本和 LibreOffice 转换的 PDF，方便对照

**任务管理**
- **任务队列**：3 级优先级队列（管理员 > API > 普通用户），可配置并发数
- **两阶段进度**：Office 文档显示「转换PDF」和「OCR识别」两阶段进度，图片/PDF 单进度条
- **实时进度**：WebSocket 推送 + HTTP 轮询降级，基于历史数据的进度估算
- **批量操作**：多文件同时上传、批量下载打包、批量删除

**系统管理**
- **管理后台**：用户管理、API Key 管理（创建/吊销/查看/复制）
- **在线配置**：超时时间、并发数等配置在管理面板在线修改，立即生效无需重启，自动持久化到 .env
- **日志查看**：管理面板实时查看系统运行日志，按级别着色，支持自动刷新
- **SSO 登录**：支持 OOS 统一登录，管理员白名单配置

**技术特性**
- **流式传输**：分片上传（4MB chunks）+ 分片 base64 编码，支持大文件
- **Docker 部署**：Dockerfile 含 LibreOffice，一键构建部署

---

## 快速开始

### Docker 部署（推荐）

```bash
cd docker
docker compose up -d --build
```

或手动构建：

```bash
docker build -t paddleocr-ui -f docker/Dockerfile .
docker run -d -p 5553:5553 \
  -v ./data:/app/data \
  -e DB_HOST=your-db-host \
  -e DB_PASSWORD=your-password \
  paddleocr-ui
```

### 手动部署

**依赖：**
- Python 3.12+
- PostgreSQL（或 openGauss-lite）
- LibreOffice（可选，Office 格式转换需要）
- Node.js 18+（前端构建）

```bash
# 安装后端依赖
pip install -r requirements.txt

# 构建前端
cd frontend && npm install && npm run build && cp -r dist/* ../static/

# 配置
cp .env.example .env
# 编辑 .env 填入实际配置

# 初始化数据库
python -m backend.init_db

# 启动
python -m backend.main
```

访问 http://localhost:5553 即可使用。

---

## 支持格式

### 直接 OCR 识别

| 格式 | 说明 |
|--------|---------|
| pdf | PDF 文档 |
| jpg / jpeg | JPEG 图片 |
| png | PNG 图片 |
| bmp | BMP 图片 |
| tiff / tif | TIFF 图片 |
| webp | WebP 图片 |

### LibreOffice 转换后识别

| 格式 | 说明 |
|--------|---------|
| doc / docx | Word 文档 |
| xls / xlsx | Excel 表格 |
| ppt / pptx | PowerPoint 演示文稿 |
| odt / ods / odp | OpenDocument 格式 |
| rtf / csv / txt / html | 其他文档 |

---

## API 使用

### 认证

所有 API 请求需携带 API Key：

```
X-API-Key: ak_xxxxxxxxxxxxx
```

### 提交任务

```bash
curl -X POST http://localhost:5553/api/v1/tasks \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@document.pdf" \
  -F "task_type=ocr" \
  -F 'output_formats=["markdown","json"]'
```

### 查询状态

```bash
curl http://localhost:5553/api/v1/tasks/98 -H "X-API-Key: YOUR_KEY"
```

### 下载结果

```bash
# ZIP 打包（含源文件+图片+结果）
curl -O http://localhost:5553/api/v1/files/98/download?format=zip \
  -H "X-API-Key: YOUR_KEY"

# 其他格式：md, json, txt, docx
curl -O http://localhost:5553/api/v1/files/98/download?format=json \
  -H "X-API-Key: YOUR_KEY"
```

详细 API 文档见 [docs/API.md](docs/API.md)，完整使用说明见 [docs/使用说明.md](docs/使用说明.md)。

---

## 系统架构

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

- **前端**: Vue 3 + Element Plus + Pinia
- **后端**: FastAPI + SQLAlchemy async + WebSocket
- **OCR 引擎**: PaddleOCR HPS 产线服务
- **文档转换**: LibreOffice headless
- **任务队列**: asyncio.PriorityQueue（3 级优先级）

---

## 管理后台

| 模块 | 功能 |
|--------|---------|
| 用户管理 | 查看用户、设置管理员权限 |
| API Key 管理 | 创建、吊销、查看 Key |
| 系统设置 | 超时配置、并发数（在线修改立即生效） |
| 系统日志 | 实时查看运行日志，按级别着色 |

---

## 配置项

所有配置通过 `.env` 文件或环境变量设置，详见 [.env.example](.env.example)。

---

## 许可证

MIT
