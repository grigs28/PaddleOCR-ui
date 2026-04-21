import os
from collections import deque
from fastapi import APIRouter, Request, Query

from backend.api.admin_router import _require_admin
from backend.config import get_settings

router = APIRouter(prefix="/api/v1/admin", tags=["管理后台"])


@router.get("/logs")
async def get_logs(request: Request, lines: int = Query(200, ge=10, le=2000)):
    """读取最近 N 行日志"""
    await _require_admin(request)
    settings = get_settings()
    log_path = settings.log_file

    if not os.path.exists(log_path):
        return {"logs": [], "total": 0}

    # 高效读取文件末尾 N 行
    with open(log_path, "r", encoding="utf-8", errors="replace") as f:
        tail_lines = deque(f, maxlen=lines)

    return {"logs": list(tail_lines), "total": len(tail_lines)}
