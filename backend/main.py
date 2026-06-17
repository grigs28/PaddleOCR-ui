import os
import logging
from logging.handlers import RotatingFileHandler
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.api.auth_router import router as auth_router
from backend.api.ocr_router import router as ocr_router
from backend.api.ws_router import router as ws_router
from backend.api.file_router import router as file_router
from backend.api.admin_router import router as admin_router
from backend.api.admin_settings_router import router as admin_settings_router
from backend.api.admin_log_router import router as admin_log_router
from backend.services.task_engine import task_engine

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')


def _sync_env_file(settings):
    """确保容器内 .env 文件包含所有配置（从环境变量补充缺失项）"""
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    env_path = os.path.normpath(env_path)

    existing = {}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()

    # 从 pydantic settings 所有字段补充
    changed = False
    for field_name in settings.model_fields:
        val = str(getattr(settings, field_name))
        if field_name not in existing:
            existing[field_name] = val
            changed = True

    if changed:
        with open(env_path, "w", encoding="utf-8") as f:
            for k, v in existing.items():
                f.write(f"{k}={v}\n")


async def _auto_migrate():
    """自动建表 + 新增列迁移"""
    from backend.database import engine, Base
    from backend.models import task, user, api_key  # noqa: 确保模型注册

    # 建表（不覆盖已存在的表）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 增量迁移：检查并添加缺失的列
    async with engine.begin() as conn:
        # 获取 tasks 表现有列
        result = await conn.execute(
            __import__('sqlalchemy').text(
                "SELECT column_name FROM information_schema.columns WHERE table_name='tasks'"
            )
        )
        existing_cols = {row[0] for row in result.fetchall()}

        # 模型定义的列
        from backend.models.task import Task
        model_cols = {c.name for c in Task.__table__.columns}

        # 添加缺失列
        for col_name in model_cols - existing_cols:
            col = Task.__table__.columns[col_name]
            col_type = str(col.type).upper()
            default = ""
            if col.default is not None:
                val = col.default.arg
                # 字符串类型 default 需加单引号（VARCHAR/CHAR/TEXT）
                if isinstance(val, str) or any(t in col_type for t in ("VARCHAR", "CHAR", "TEXT")):
                    default = f" DEFAULT '{val}'"
                else:
                    default = f" DEFAULT {val}"
            elif col.server_default is not None:
                default = f" DEFAULT {col.server_default.arg}"
            sql = f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}{default}"
            logging.getLogger(__name__).info(f"迁移: {sql}")
            await conn.execute(__import__('sqlalchemy').text(sql))
async def lifespan(app: FastAPI):
    settings = get_settings()
    # 启动时同步环境变量到 .env 文件（确保容器内 .env 完整）
    _sync_env_file(settings)
    for dir_path in [settings.upload_dir, settings.result_dir, settings.temp_dir]:
        os.makedirs(dir_path, exist_ok=True)
    # 文件日志
    os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)
    file_handler = RotatingFileHandler(
        settings.log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(file_handler)

    # 自动迁移：同步模型字段到数据库
    await _auto_migrate()

    await task_engine.start()
    yield
    await task_engine.stop()


app = FastAPI(
    title="PaddleOCR Web UI",
    description="基于 PaddleOCR-VL 的 Web OCR 服务",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


# 注册 API 路由
app.include_router(auth_router)
app.include_router(ocr_router)
app.include_router(ws_router)
app.include_router(file_router)
app.include_router(admin_router)
app.include_router(admin_settings_router)
app.include_router(admin_log_router)

# 静态文件服务（前端构建产物）— 必须放在所有路由之后
_static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if not os.path.isdir(_static_dir):
    _static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend", "dist")
if os.path.isdir(_static_dir):
    from starlette.staticfiles import StaticFiles
    # 自定义 StaticFiles 禁用缓存，确保前端更新后浏览器加载最新版本
    class NoCacheStaticFiles(StaticFiles):
        async def __call__(self, scope, receive, send):
            async def _send(message):
                if message["type"] == "http.response.start":
                    headers = list(message.get("headers", []))
                    headers.append((b"cache-control", b"no-cache, no-store, must-revalidate"))
                    message["headers"] = headers
                await send(message)
            await super().__call__(scope, receive, _send)
    app.mount("/", NoCacheStaticFiles(directory=_static_dir, html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run("backend.main:app", host=settings.app_host, port=settings.app_port, reload=True)
