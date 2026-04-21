#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 检查 .env
if [ ! -f .env ]; then
    echo "从 .env.example 创建 .env..."
    cp .env.example .env
    echo "请编辑 .env 配置后再启动"
    exit 1
fi

# 检查前端构建
if [ ! -d frontend/dist ]; then
    echo "构建前端..."
    cd frontend && npm install && npm run build && cd ..
fi

# 创建数据目录
mkdir -p data/uploads data/results data/temp

# 初始化数据库
echo "初始化数据库..."
python -m backend.init_db

# 启动服务
echo "启动 PaddleOCR Web UI (端口 5553)..."
exec uvicorn backend.main:app --host 0.0.0.0 --port 5553 --workers 1
