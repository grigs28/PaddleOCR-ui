import os
from fastapi import APIRouter, Request

from backend.api.admin_router import _require_admin
from backend.config import get_settings

router = APIRouter(prefix="/api/v1/admin", tags=["管理后台"])

# 可通过管理面板修改的配置项及其描述
EDITABLE_SETTINGS = {
    "ocr_image_timeout": {"label": "图片 OCR 超时（秒）", "type": "int", "min": 10, "max": 3600},
    "ocr_pdf_page_timeout": {"label": "PDF 每页超时（秒）", "type": "int", "min": 5, "max": 600},
    "libreoffice_timeout": {"label": "LibreOffice 转换超时（秒）", "type": "int", "min": 60, "max": 7200},
    "ocr_health_timeout": {"label": "健康检查超时（秒）", "type": "int", "min": 1, "max": 60},
    "image_semaphore_size": {"label": "图片并发数", "type": "int", "min": 1, "max": 20},
    "pdf_semaphore_size": {"label": "PDF 并发数", "type": "int", "min": 1, "max": 20},
    "max_file_size_mb": {"label": "最大文件大小（MB）", "type": "int", "min": 1, "max": 10240},
}


@router.get("/settings")
async def get_admin_settings(request: Request):
    """获取可编辑的系统配置"""
    await _require_admin(request)
    settings = get_settings()
    result = {}
    for key, meta in EDITABLE_SETTINGS.items():
        result[key] = {
            "value": getattr(settings, key),
            "label": meta["label"],
            "type": meta["type"],
            "min": meta["min"],
            "max": meta["max"],
        }
    return {"settings": result}


@router.put("/settings")
async def update_admin_settings(request: Request):
    """更新系统配置（热生效 + 持久化到 .env）"""
    await _require_admin(request)
    body = await request.json()
    settings = get_settings()

    updated = {}
    for key, value in body.items():
        if key not in EDITABLE_SETTINGS:
            continue
        meta = EDITABLE_SETTINGS[key]
        # 类型转换和范围校验
        if meta["type"] == "int":
            value = int(value)
            value = max(meta["min"], min(meta["max"], value))
        setattr(settings, key, value)
        updated[key] = value

    # 持久化到 .env 文件
    _save_to_env(updated)

    return {"message": f"已更新 {len(updated)} 项配置", "updated": updated}


def _save_to_env(updates: dict):
    """将配置变更持久化到 .env 文件"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

    # 读取现有 .env
    existing = {}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()

    # 更新值
    for key, value in updates.items():
        existing[key] = str(value)

    # 写回
    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")
