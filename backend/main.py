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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    for dir_path in [settings.upload_dir, settings.result_dir, settings.temp_dir]:
        os.makedirs(dir_path, exist_ok=True)
    # 文件日志
    os.makedirs(os.path.dirname(settings.log_file), exist_ok=True)
    file_handler = RotatingFileHandler(
        settings.log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter('%(asctime)s %(name)s %(levelname)s %(message)s'))
    logging.getLogger().addHandler(file_handler)

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
