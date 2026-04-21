FROM python:3.12-slim

WORKDIR /app

# 安装系统依赖 + LibreOffice（headless 模式）
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libreoffice-writer-nogui \
    libreoffice-calc-nogui \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制后端代码
COPY backend/ backend/

# 复制前端构建产物
COPY frontend/dist/ static/

# 创建数据目录
RUN mkdir -p data/uploads data/results data/temp

# 暴露端口
EXPOSE 5553

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "5553"]
