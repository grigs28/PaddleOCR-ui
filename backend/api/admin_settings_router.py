import os
import shutil
from fastapi import APIRouter, Request

from backend.api.admin_router import _require_admin
from backend.config import get_settings

router = APIRouter(prefix="/api/v1/admin", tags=["管理后台"])

# 可通过管理面板修改的配置项及其描述
EDITABLE_SETTINGS = {
    # 超时配置
    "ocr_image_timeout": {"label": "图片 OCR 超时（秒）", "type": "int", "min": 10, "max": 3600},
    "ocr_pdf_page_timeout": {"label": "PDF 每页超时（秒）", "type": "int", "min": 5, "max": 600},
    "libreoffice_timeout": {"label": "LibreOffice 转换超时（秒）", "type": "int", "min": 60, "max": 7200},
    "ocr_health_timeout": {"label": "健康检查超时（秒）", "type": "int", "min": 1, "max": 60},
    "acad_task_timeout": {"label": "ACAD 轮询超时（秒）", "type": "int", "min": 60, "max": 7200},
    # 并发配置
    "image_semaphore_size": {"label": "图片并发数", "type": "int", "min": 1, "max": 20},
    "pdf_semaphore_size": {"label": "PDF 并发数", "type": "int", "min": 1, "max": 20},
    "acad_concurrency": {"label": "ACAD 并发数", "type": "int", "min": 1, "max": 20},
    # 文件与会话配置
    "max_file_size_mb": {"label": "最大文件大小（MB）", "type": "int", "min": 1, "max": 10240},
    "chunk_size": {"label": "上传分片大小（MB）", "type": "int", "min": 1, "max": 64, "transform": "mb_to_bytes"},
    "session_expire_hours": {"label": "会话过期时间（小时）", "type": "int", "min": 1, "max": 168},
    # 服务地址
    "db_host": {"label": "数据库地址", "type": "str"},
    "db_port": {"label": "数据库端口", "type": "int", "min": 1, "max": 65535},
    "db_user": {"label": "数据库用户", "type": "str"},
    "db_password": {"label": "数据库密码", "type": "str"},
    "db_name": {"label": "数据库名称", "type": "str"},
    "ocr_service_url": {"label": "OCR 服务地址", "type": "str"},
    "acad_service_url": {"label": "DWG→PDF/DXF 服务地址", "type": "str"},
    "acad_service_apikey": {"label": "DWG→PDF/DXF API Key", "type": "str"},
    "yz_login_url": {"label": "SSO 登录地址", "type": "str"},
    "callback_url": {"label": "SSO 回调地址", "type": "str"},
}


@router.get("/settings")
async def get_admin_settings(request: Request):
    """获取可编辑的系统配置"""
    await _require_admin(request)
    settings = get_settings()
    result = {}
    for key, meta in EDITABLE_SETTINGS.items():
        entry = {
            "value": getattr(settings, key) // (1024 * 1024) if meta.get("transform") == "mb_to_bytes" else getattr(settings, key),
            "label": meta["label"],
            "type": meta["type"],
        }
        if "min" in meta:
            entry["min"] = meta["min"]
        if "max" in meta:
            entry["max"] = meta["max"]
        result[key] = entry
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
            # MB → bytes
            if meta.get("transform") == "mb_to_bytes":
                setattr(settings, key, value * 1024 * 1024)
                updated[key] = value * 1024 * 1024
                continue
        setattr(settings, key, value)
        updated[key] = value

    # 持久化到 .env 文件
    _save_to_env(updated)

    # 如果修改了并发数，刷新 task_engine 信号量
    concurrency_keys = {"image_semaphore_size", "pdf_semaphore_size", "acad_concurrency"}
    if concurrency_keys & set(updated.keys()):
        from backend.services.task_engine import task_engine
        task_engine.refresh_semaphores()

    return {"message": f"已更新 {len(updated)} 项配置", "updated": updated}


def _save_to_env(updates: dict):
    """将配置变更持久化到 .env 文件"""
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")

    # 读取现有 .env（包含原始启动配置）
    existing = {}
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()

    # 也从当前环境变量补充（--env-file 注入的可能不在文件中）
    import os as _os
    for key in updates:
        env_key = key.upper()
        env_val = _os.environ.get(env_key)
        if env_val is not None and key not in existing:
            existing[key] = env_val

    # 更新值
    for key, value in updates.items():
        existing[key] = str(value)

    # 写回
    with open(env_path, "w", encoding="utf-8") as f:
        for k, v in existing.items():
            f.write(f"{k}={v}\n")


@router.post("/test-connection")
async def test_service_connection(request: Request):
    """测试外部服务连通性"""
    await _require_admin(request)
    body = await request.json()
    service = body.get("service", "")
    import httpx

    if service == "ocr":
        url = get_settings().ocr_service_url.rstrip("/")
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{url}/health")
                if resp.status_code == 200:
                    return {"ok": True, "message": f"OCR 服务连接正常 ({url})"}
                return {"ok": False, "message": f"OCR 服务返回 {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "message": f"连接失败: {e}"}

    elif service == "acad":
        settings = get_settings()
        url = settings.acad_service_url.rstrip("/")
        headers = {}
        if settings.acad_service_apikey:
            headers["x-api-key"] = settings.acad_service_apikey
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{url}/health", headers=headers)
                if resp.status_code == 200:
                    return {"ok": True, "message": f"DWG 转换服务连接正常 ({url})"}
                return {"ok": False, "message": f"服务返回 {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "message": f"连接失败: {e}"}

    return {"ok": False, "message": f"未知服务: {service}"}


@router.post("/clear-tasks")
async def clear_all_tasks(request: Request):
    """清空所有任务（数据库 + 文件）"""
    await _require_admin(request)
    from backend.database import async_session
    from backend.models.task import Task
    from sqlalchemy import delete, select

    # 获取所有结果路径和上传路径，用于删文件
    async with async_session() as s:
        r = await s.execute(select(Task.result_path, Task.input_file_path))
        paths = r.fetchall()
        await s.execute(delete(Task))
        await s.commit()

    # 清理文件
    removed = 0
    for result_path, input_path in paths:
        if result_path and os.path.isdir(result_path):
            shutil.rmtree(result_path, ignore_errors=True)
            removed += 1
        if input_path and os.path.exists(input_path):
            parent = os.path.dirname(input_path)
            if os.path.isdir(parent):
                shutil.rmtree(parent, ignore_errors=True)
                removed += 1

    return {"message": f"已清空 {len(paths)} 条任务，删除 {removed} 个目录"}
