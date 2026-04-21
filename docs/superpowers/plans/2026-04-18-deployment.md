# 部署配置实施计划

**日期**: 2026-04-18
**状态**: 待执行
**负责人**: deployment-agent
**关联设计**: [PaddleOCR UI 设计文档](../specs/2026-04-18-paddleocr-ui-design.md)

---

## 概述

本计划覆盖 PaddleOCR-UI 项目的所有部署和基础设施配置文件，包括依赖管理、容器化、反向代理、系统服务、启动脚本和前端构建配置。

**外部服务连接信息：**
- 数据库：openGauss-lite 7.0.0-RC1 @ `192.168.0.98:5432`，用户 `grigs/Slnwg123$`
- OCR 服务：PaddleOCR-VL @ `http://192.168.0.70:5564/v1`
- 认证服务：yz-login @ `http://192.168.0.19:5555`

---

## Task 1: requirements.txt

**目标**: 完整的 Python 依赖清单，锁定版本号确保可重复构建。

**文件路径**: `/opt/webapp/PaddleOCR-ui/requirements.txt`

**完整内容**:

```txt
# Web 框架
fastapi==0.115.12
uvicorn[standard]==0.34.2

# 数据库
sqlalchemy[asyncio]==2.0.40
asyncpg==0.30.0

# 文件处理
python-multipart==0.0.20

# HTTP 客户端（调用 OCR 服务）
aiohttp==3.11.18

# 配置管理
pydantic-settings==2.9.1

# 文档处理
python-docx==1.1.2
openpyxl==3.1.5

# PDF 处理
PyMuPDF==1.25.5

# 格式转换
pandoc==2.4

# 认证
pyjwt==2.10.1

# 工具
python-dateutil==2.9.0
```

**验证步骤**:
1. `pip install -r requirements.txt` 无报错
2. `python -c "import fastapi; import sqlalchemy; import asyncpg; import aiohttp"` 成功
3. 在干净虚拟环境中测试安装

**Commit**: `feat: add Python dependencies (requirements.txt)`

---

## Task 2: Dockerfile

**目标**: 多阶段构建，前端用 Node.js 编译，后端用 Python 运行，镜像尽量小。

**文件路径**: `/opt/webapp/PaddleOCR-ui/Dockerfile`

**完整内容**:

```dockerfile
# ===== 阶段 1: 构建前端 =====
FROM node:18-alpine AS frontend-builder

WORKDIR /build/frontend

# 先复制依赖文件，利用 Docker 缓存
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com

# 复制前端源码并构建
COPY frontend/ ./
RUN npm run build

# ===== 阶段 2: 构建运行时镜像 =====
FROM python:3.11-slim AS runtime

# 安装系统依赖（pandoc 用于 Markdown → DOCX 转换）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        pandoc \
        libgl1-mesa-glx \
        libglib2.0-0 \
        curl && \
    rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制后端代码
COPY backend/ ./backend/

# 从前端构建阶段复制产物
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist/

# 创建数据目录并设置权限
RUN mkdir -p /app/data/uploads /app/data/results /app/data/temp && \
    chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 暴露端口
EXPOSE 8080

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/api/health || exit 1

# 启动命令
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
```

**验证步骤**:
1. `docker build -t paddleocr-ui:test .` 构建成功
2. `docker images paddleocr-ui:test` 检查镜像大小（目标 < 500MB）
3. `docker run --rm paddleocr-ui:test python -c "import fastapi"` 验证依赖
4. `docker run --rm -p 8080:8080 paddleocr-ui:test` 启动无报错
5. 验证健康检查端点正常响应

**Commit**: `feat: add multi-stage Dockerfile`

---

## Task 3: docker-compose.yml

**目标**: 一键启动完整服务，包含环境变量、持久化和重启策略。

**文件路径**: `/opt/webapp/PaddleOCR-ui/docker-compose.yml`

**完整内容**:

```yaml
version: "3.8"

services:
  paddleocr-ui:
    build:
      context: .
      dockerfile: Dockerfile
    image: paddleocr-ui:latest
    container_name: paddleocr-ui
    ports:
      - "8080:8080"
    environment:
      # 数据库配置（openGauss）
      - DB_HOST=192.168.0.98
      - DB_PORT=5432
      - DB_USER=grigs
      - DB_PASSWORD=Slnwg123$
      - DB_NAME=paddleocr_ui
      # OCR 服务配置
      - OCR_SERVICE_URL=http://192.168.0.70:5564/v1
      - OCR_MODEL_NAME=PaddleOCR-VL-1.5-0.9B
      # 认证服务配置
      - YZ_LOGIN_URL=http://192.168.0.19:5555
      - APP_BASE_URL=http://localhost:8080
      # 应用配置
      - APP_ENV=production
      - LOG_LEVEL=info
      - MAX_FILE_SIZE_MB=100
      - MAX_CONCURRENCY=3
      - SECRET_KEY=change-me-in-production
    volumes:
      - ./data/uploads:/app/data/uploads
      - ./data/results:/app/data/results
      - ./data/temp:/app/data/temp
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 15s
    networks:
      - paddleocr-net

networks:
  paddleocr-net:
    driver: bridge
```

**验证步骤**:
1. `docker-compose config` 验证 YAML 语法正确
2. `docker-compose up -d` 启动服务
3. `docker-compose ps` 状态为 healthy
4. `curl http://localhost:8080/api/health` 返回 200
5. `docker-compose logs paddleocr-ui` 无错误日志
6. 验证数据目录 `./data/` 正确创建
7. `docker-compose down` 清理后数据目录保留

**Commit**: `feat: add docker-compose.yml`

---

## Task 4: .env.example

**目标**: 环境变量模板，包含所有配置项的说明和默认值。

**文件路径**: `/opt/webapp/PaddleOCR-ui/.env.example`

**完整内容**:

```env
# ===========================
# PaddleOCR-UI 环境变量配置
# ===========================
# 复制此文件为 .env 并根据实际环境修改

# ---------- 数据库配置 ----------
# openGauss 数据库连接信息
DB_HOST=192.168.0.98
DB_PORT=5432
DB_USER=grigs
DB_PASSWORD=Slnwg123$
DB_NAME=paddleocr_ui

# 数据库连接池大小
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

# ---------- OCR 服务配置 ----------
# PaddleOCR-VL 服务地址（OpenAI 兼容 API）
OCR_SERVICE_URL=http://192.168.0.70:5564/v1
OCR_MODEL_NAME=PaddleOCR-VL-1.5-0.9B

# 单次 OCR 请求超时（秒）
OCR_REQUEST_TIMEOUT=120

# ---------- 认证服务配置 ----------
# yz-login 服务地址
YZ_LOGIN_URL=http://192.168.0.19:5555

# 应用自身的外部访问地址（用于 yz-login 回调）
APP_BASE_URL=http://localhost:8080

# Session 加密密钥（生产环境必须修改为随机字符串）
SECRET_KEY=change-me-in-production

# Session 过期时间（小时）
SESSION_EXPIRE_HOURS=24

# ---------- 应用配置 ----------
# 运行环境: development / production
APP_ENV=production

# 日志级别: debug / info / warning / error
LOG_LEVEL=info

# 服务监听端口
APP_PORT=8080

# ---------- 文件处理配置 ----------
# 最大上传文件大小（MB）
MAX_FILE_SIZE_MB=100

# 允许的文件类型（逗号分隔）
ALLOWED_FILE_TYPES=pdf,jpg,jpeg,png,bmp,tiff,tif,docx,xlsx

# 数据存储根目录
DATA_DIR=./data

# 临时文件清理间隔（小时）
TEMP_CLEANUP_HOURS=24

# ---------- 任务引擎配置 ----------
# 最大并发 OCR 任务数
MAX_CONCURRENCY=3

# 队列暂停状态（0=正常，1=暂停）
QUEUE_PAUSED=0
```

**验证步骤**:
1. `cp .env.example .env` 复制无报错
2. 对比 docker-compose.yml 中的环境变量是否都在 .env.example 中有对应
3. 所有默认值合理，注释清晰

**Commit**: `feat: add .env.example with all configuration options`

---

## Task 5: systemd service

**目标**: 裸机部署的系统服务配置。

**文件路径**: `/opt/webapp/PaddleOCR-ui/deploy/paddleocr-ui.service`

**完整内容**:

```ini
[Unit]
Description=PaddleOCR Web UI Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=grigs
Group=grigs
WorkingDirectory=/opt/webapp/PaddleOCR-ui

# 环境变量
EnvironmentFile=/opt/webapp/PaddleOCR-ui/.env

# 启动命令
ExecStart=/opt/webapp/PaddleOCR-ui/venv/bin/uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers 1 \
    --log-level info \
    --access-log

# 优雅停止
KillSignal=SIGTERM
TimeoutStopSec=30

# 重启策略
Restart=on-failure
RestartSec=10

# 安全限制
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/webapp/PaddleOCR-ui/data
PrivateTmp=true

# 日志输出到 journalctl
StandardOutput=journal
StandardError=journal
SyslogIdentifier=paddleocr-ui

[Install]
WantedBy=multi-user.target
```

**安装说明**:
```bash
# 复制 service 文件
sudo cp deploy/paddleocr-ui.service /etc/systemd/system/

# 重新加载 systemd
sudo systemctl daemon-reload

# 启用开机自启
sudo systemctl enable paddleocr-ui

# 启动服务
sudo systemctl start paddleocr-ui

# 查看状态
sudo systemctl status paddleocr-ui

# 查看日志
journalctl -u paddleocr-ui -f
```

**验证步骤**:
1. 文件语法正确，`systemd-analyze verify paddleocr-ui.service` 无错误
2. `systemctl start paddleocr-ui` 启动成功
3. `systemctl status paddleocr-ui` 显示 active (running)
4. 重启机器后服务自动启动

**Commit**: `feat: add systemd service file for bare-metal deployment`

---

## Task 6: nginx 配置

**目标**: 反向代理配置，包含静态文件缓存、WebSocket 代理和文件上传大小限制。

**文件路径**: `/opt/webapp/PaddleOCR-ui/deploy/paddleocr-ui.conf`

**完整内容**:

```nginx
upstream paddleocr_ui {
    server 127.0.0.1:8080;
    keepalive 32;
}

server {
    listen 80;
    server_name _;

    # 如需 HTTPS，取消注释以下配置并配置证书
    # listen 443 ssl http2;
    # ssl_certificate     /etc/nginx/ssl/paddleocr-ui.crt;
    # ssl_certificate_key /etc/nginx/ssl/paddleocr-ui.key;
    # ssl_protocols       TLSv1.2 TLSv1.3;

    # 安全头
    add_header X-Content-Type-Options nosniff always;
    add_header X-Frame-Options SAMEORIGIN always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;

    # 文件上传大小限制（与 MAX_FILE_SIZE_MB 对应）
    client_max_body_size 100m;

    # 请求体缓冲
    client_body_buffer_size 128k;

    # 代理超时设置（OCR 任务可能耗时较长）
    proxy_connect_timeout 60s;
    proxy_send_timeout 300s;
    proxy_read_timeout 300s;

    # WebSocket 代理
    location /ws/ {
        proxy_pass http://paddleocr_ui;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    # API 请求代理
    location /api/ {
        proxy_pass http://paddleocr_ui;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
    }

    # 登录回调代理
    location /auth/ {
        proxy_pass http://paddleocr_ui;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 前端静态文件（从后端提供，设置缓存）
    location /assets/ {
        proxy_pass http://paddleocr_ui;
        proxy_set_header Host $host;
        expires 7d;
        add_header Cache-Control "public, immutable";
    }

    # 其他所有请求代理到后端
    location / {
        proxy_pass http://paddleocr_ui;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 禁止访问隐藏文件
    location ~ /\. {
        deny all;
        return 404;
    }
}
```

**安装说明**:
```bash
# 复制配置文件
sudo cp deploy/paddleocr-ui.conf /etc/nginx/conf.d/

# 测试配置
sudo nginx -t

# 重新加载 nginx
sudo systemctl reload nginx
```

**验证步骤**:
1. `nginx -t` 语法检查通过
2. `curl http://localhost/api/health` 返回 200
3. WebSocket 连接 `ws://localhost/ws/progress` 正常
4. 上传 100MB 文件不被拒绝
5. 静态资源 `/assets/` 响应头包含缓存控制

**Commit**: `feat: add nginx reverse proxy configuration`

---

## Task 7: 启动脚本

**目标**: 一键启动脚本，包含环境检查、依赖安装、数据库初始化和启动服务。

**文件路径**: `/opt/webapp/PaddleOCR-ui/start.sh`

**完整内容**:

```bash
#!/usr/bin/env bash
set -euo pipefail

# ===========================
# PaddleOCR-UI 启动脚本
# ===========================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------- 加载环境变量 ----------
if [ -f .env ]; then
    set -a
    source .env
    set +a
    log_info "已加载 .env 配置"
else
    log_warn ".env 文件不存在，请复制 .env.example 并修改"
    log_warn "  cp .env.example .env"
    exit 1
fi

# ---------- 环境检查 ----------
check_command() {
    if ! command -v "$1" &>/dev/null; then
        log_error "未找到命令: $1，请先安装"
        exit 1
    fi
}

log_info "检查运行环境..."
check_command python3
check_command pip

# Python 版本检查
PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
log_info "Python 版本: $PY_VERSION"

# ---------- 创建虚拟环境 ----------
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    log_info "创建 Python 虚拟环境..."
    python3 -m venv "$VENV_DIR"
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"
log_info "已激活虚拟环境"

# ---------- 安装依赖 ----------
if [ -f requirements.txt ]; then
    log_info "检查 Python 依赖..."
    pip install -q -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    log_info "Python 依赖安装完成"
else
    log_error "requirements.txt 不存在"
    exit 1
fi

# ---------- 前端构建 ----------
FRONTEND_DIR="$SCRIPT_DIR/frontend"
if [ -d "$FRONTEND_DIR" ] && [ ! -d "$FRONTEND_DIR/dist" ]; then
    log_info "构建前端..."
    check_command node
    check_command npm

    cd "$FRONTEND_DIR"
    npm ci --registry=https://registry.npmmirror.com
    npm run build
    cd "$SCRIPT_DIR"
    log_info "前端构建完成"
elif [ -d "$FRONTEND_DIR/dist" ]; then
    log_info "前端已构建，跳过（删除 frontend/dist 可重新构建）"
fi

# ---------- 创建数据目录 ----------
mkdir -p data/uploads data/results data/temp
log_info "数据目录已就绪"

# ---------- 数据库初始化 ----------
log_info "初始化数据库..."
python3 -c "
import asyncio
from backend.database import init_db

async def main():
    await init_db()
    print('数据库初始化完成')

asyncio.run(main())
" || log_warn "数据库初始化失败，请检查数据库连接配置"

# ---------- 启动服务 ----------
APP_PORT="${APP_PORT:-8080}"
LOG_LEVEL="${LOG_LEVEL:-info}"
WORKERS="${WORKERS:-1}"

log_info "启动 PaddleOCR-UI 服务 (端口: $APP_PORT)..."
exec uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port "$APP_PORT" \
    --workers "$WORKERS" \
    --log-level "$LOG_LEVEL" \
    --access-log
```

**验证步骤**:
1. `chmod +x start.sh` 赋予执行权限
2. `./start.sh` 在正确配置环境下启动成功
3. 缺少 .env 时给出明确提示
4. 缺少 Python 时给出明确提示
5. 虚拟环境正确创建和激活

**Commit**: `feat: add one-click start script`

---

## Task 8: 前端 package.json

**目标**: Vue 3 前端项目配置，包含完整的依赖和脚本。

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/package.json`

**完整内容**:

```json
{
  "name": "paddleocr-ui-frontend",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "vue": "^3.5.13",
    "vue-router": "^4.5.0",
    "pinia": "^2.3.0",
    "axios": "^1.9.0",
    "@vueuse/core": "^12.7.0",
    "element-plus": "^2.9.6"
  },
  "devDependencies": {
    "@vitejs/plugin-vue": "^5.2.3",
    "vite": "^6.3.2"
  }
}
```

**配套的 Vite 配置文件**:

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/vite.config.js`

```javascript
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:8080',
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
  },
})
```

**配套的 HTML 入口文件**:

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/index.html`

```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>PaddleOCR Web UI</title>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="/src/main.js"></script>
  </body>
</html>
```

**验证步骤**:
1. `cd frontend && npm install` 安装依赖成功
2. `npm run dev` 开发服务器启动在 3000 端口
3. `npm run build` 构建到 dist/ 目录
4. `npm run preview` 预览构建结果
5. API 代理配置正确，请求转发到 8080

**Commit**: `feat: add frontend package.json with Vue 3 dependencies`

---

## Task 9: .gitignore

**目标**: 覆盖 Python、Node.js、IDE、数据目录的忽略规则。

**文件路径**: `/opt/webapp/PaddleOCR-ui/.gitignore`

**完整内容**:

```gitignore
# ===== Python =====
__pycache__/
*.py[cod]
*$py.class
*.so
*.egg-info/
*.egg
dist/
build/
.eggs/
venv/
.venv/
env/
*.whl

# ===== Node.js =====
node_modules/
frontend/dist/
frontend/node_modules/
npm-debug.log*
yarn-debug.log*
yarn-error.log*
pnpm-debug.log*

# ===== IDE =====
.vscode/
.idea/
*.swp
*.swo
*~
.project
.classpath
.settings/
*.sublime-project
*.sublime-workspace

# ===== 环境配置 =====
.env
.env.local
.env.*.local

# ===== 数据目录 =====
data/
uploads/
results/
temp/

# ===== 日志 =====
*.log
logs/

# ===== OS =====
.DS_Store
Thumbs.db
desktop.ini

# ===== Docker =====
docker-compose.override.yml

# ===== 测试 =====
.coverage
htmlcov/
.pytest_cache/
.mypy_cache/
```

**验证步骤**:
1. `.env` 文件不会被 git 跟踪
2. `data/` 目录不会被 git 跟踪
3. `node_modules/` 不会被 git 跟踪
4. `__pycache__/` 不会被 git 跟踪
5. `.env.example` 会被 git 跟踪（不在忽略列表中）

**Commit**: `feat: add .gitignore for Python, Node.js, IDE and data dirs`

---

## Task 10: 项目 README.md

**目标**: 项目介绍、快速开始（Docker 和裸机两种方式）、环境变量说明、API 文档链接。

**文件路径**: `/opt/webapp/PaddleOCR-ui/README.md`

**完整内容**:

```markdown
# PaddleOCR Web UI

基于 PaddleOCR-VL-1.5-0.9B 模型的 Web OCR 服务，支持多用户并发、异步队列处理和实时进度推送。

## 功能特性

- 多格式文件 OCR 识别（PDF、图片、Word、Excel）
- 多种输出格式（Markdown、JSON、TXT、DOCX）
- 表格、公式、图表专项识别
- 异步任务队列，实时进度推送（WebSocket）
- 多用户认证（yz-login + API Key）
- REST API 支持外部系统集成

## 快速开始

### 方式一：Docker 部署（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/grigs28/PaddleOCR-ui.git
cd PaddleOCR-ui

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 修改数据库、OCR 服务等配置

# 3. 构建并启动
docker-compose up -d

# 4. 查看日志
docker-compose logs -f paddleocr-ui

# 5. 访问服务
# http://localhost:8080
```

### 方式二：裸机部署

```bash
# 1. 克隆仓库
git clone https://github.com/grigs28/PaddleOCR-ui.git
cd PaddleOCR-ui

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 修改配置

# 3. 一键启动（自动创建虚拟环境、安装依赖、初始化数据库）
chmod +x start.sh
./start.sh
```

### 方式三：systemd 服务

```bash
# 按方式二完成安装后
sudo cp deploy/paddleocr-ui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable paddleocr-ui
sudo systemctl start paddleocr-ui
```

### 方式四：nginx 反向代理

```bash
sudo cp deploy/paddleocr-ui.conf /etc/nginx/conf.d/
sudo nginx -t
sudo systemctl reload nginx
```

## 环境变量

所有配置项详见 `.env.example`，关键变量：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| DB_HOST | openGauss 数据库地址 | 192.168.0.98 |
| DB_PORT | 数据库端口 | 5432 |
| DB_USER | 数据库用户名 | grigs |
| DB_PASSWORD | 数据库密码 | - |
| DB_NAME | 数据库名 | paddleocr_ui |
| OCR_SERVICE_URL | PaddleOCR-VL 服务地址 | http://192.168.0.70:5564/v1 |
| OCR_MODEL_NAME | OCR 模型名称 | PaddleOCR-VL-1.5-0.9B |
| YZ_LOGIN_URL | yz-login 认证服务地址 | http://192.168.0.19:5555 |
| APP_BASE_URL | 应用外部访问地址 | http://localhost:8080 |
| APP_PORT | 服务监听端口 | 8080 |
| MAX_FILE_SIZE_MB | 最大上传文件大小 | 100 |
| MAX_CONCURRENCY | 最大并发 OCR 数 | 3 |

## REST API

启动服务后访问 `http://localhost:8080/docs` 查看完整 API 文档（Swagger UI）。

主要端点：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /api/v1/ocr | 提交 OCR 任务 |
| GET | /api/v1/tasks | 列出任务 |
| GET | /api/v1/tasks/{id} | 查询任务详情 |
| GET | /api/v1/tasks/{id}/result | 下载结果 |
| DELETE | /api/v1/tasks/{id} | 删除任务 |

认证方式：请求头 `X-API-Key: <api_key>`

## 外部依赖

| 服务 | 地址 | 用途 |
|------|------|------|
| PaddleOCR-VL | 192.168.0.70:5564 | OCR 推理 |
| openGauss | 192.168.0.98:5432 | 数据存储 |
| yz-login | 192.168.0.19:5555 | 用户认证 |

## 项目结构

```
PaddleOCR-ui/
├── backend/            # FastAPI 后端
│   ├── main.py         # 入口
│   ├── config.py       # 配置
│   ├── database.py     # 数据库连接
│   ├── auth/           # 认证模块
│   ├── api/            # API 路由
│   ├── services/       # 业务服务
│   ├── models/         # ORM 模型
│   └── ws/             # WebSocket
├── frontend/           # Vue 3 前端
│   ├── src/
│   │   ├── views/      # 页面
│   │   ├── components/ # 组件
│   │   ├── composables/# 组合式函数
│   │   └── stores/     # Pinia 状态
│   ├── package.json
│   └── vite.config.js
├── deploy/             # 部署配置
│   ├── paddleocr-ui.service
│   └── paddleocr-ui.conf
├── data/               # 数据目录（git 忽略）
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── start.sh
└── .env.example
```

## 许可证

私有项目，未授权禁止使用。
```

**验证步骤**:
1. Markdown 渲染正确，无语法错误
2. 所有命令可直接复制执行
3. 链接地址正确
4. 环境变量表与 .env.example 一致

**Commit**: `docs: add project README with setup instructions`

---

## 执行顺序和依赖关系

```
Task 1 (requirements.txt)
  ↓
Task 2 (Dockerfile) ─── 依赖 Task 1
  ↓
Task 3 (docker-compose.yml) ─── 依赖 Task 2
  ↓
Task 4 (.env.example) ─── 无依赖，可并行
Task 9 (.gitignore) ─── 无依赖，可并行
Task 10 (README.md) ─── 无依赖，可并行

Task 5 (systemd) ─── 依赖 Task 1
Task 6 (nginx) ─── 无依赖
Task 7 (start.sh) ─── 依赖 Task 1

Task 8 (frontend package.json) ─── 无依赖，可并行
```

**推荐并行分组**:
- **第一批**（无依赖）: Task 1, Task 4, Task 6, Task 8, Task 9, Task 10
- **第二批**（依赖第一批）: Task 2, Task 5, Task 7
- **第三批**（依赖第二批）: Task 3

## 总计文件清单

| # | 文件路径 | 类型 |
|---|---------|------|
| 1 | `requirements.txt` | Python 依赖 |
| 2 | `Dockerfile` | 容器构建 |
| 3 | `docker-compose.yml` | 容器编排 |
| 4 | `.env.example` | 环境变量模板 |
| 5 | `deploy/paddleocr-ui.service` | systemd 服务 |
| 6 | `deploy/paddleocr-ui.conf` | nginx 配置 |
| 7 | `start.sh` | 启动脚本 |
| 8 | `frontend/package.json` | 前端依赖 |
| 8b | `frontend/vite.config.js` | Vite 配置 |
| 8c | `frontend/index.html` | HTML 入口 |
| 9 | `.gitignore` | Git 忽略 |
| 10 | `README.md` | 项目文档 |
