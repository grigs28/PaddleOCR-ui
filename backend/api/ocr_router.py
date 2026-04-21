import os
import json
from fastapi import APIRouter, Request, UploadFile, File, Form, HTTPException
from sqlalchemy import select, update, desc

from backend.auth.api_key import ApiKeyManager
from backend.config import get_settings
from backend.database import async_session
from backend.models.task import Task
from backend.services.task_engine import task_engine
from backend.utils.file_utils import (
    generate_task_id, is_allowed_file, get_file_extension,
    get_upload_path, format_file_size, sanitize_filename, is_pdf_file,
)

SUPPORTED_FORMATS = {"markdown", "txt", "docx", "json", "html"}

router = APIRouter(prefix="/api/v1", tags=["OCR 任务"])


async def _get_user_id(request: Request) -> int:
    """从 Cookie 或 API Key 获取用户ID"""
    settings = get_settings()
    from backend.auth.session import SessionManager
    session_mgr = SessionManager()

    # 优先检查 Cookie
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        user = session_mgr.get_session(session_id)
        if user:
            return user["user_id"]

    # 检查 API Key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        result = await ApiKeyManager.verify_key(api_key)
        if result:
            return result["user_id"]

    raise HTTPException(status_code=401, detail="未登录或缺少 API Key")


async def _get_user_id_and_priority(request: Request) -> tuple[int, int]:
    """返回 (user_id, priority)。0=用户, 1=API, 2=管理员"""
    settings = get_settings()
    from backend.auth.session import SessionManager
    session_mgr = SessionManager()

    # Cookie 登录
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        user = session_mgr.get_session(session_id)
        if user:
            uid = user["user_id"]
            async with async_session() as s:
                from backend.models.user import User
                r = await s.execute(select(User).where(User.id == uid))
                u = r.scalar_one_or_none()
                if u and u.is_admin:
                    return uid, 2  # 管理员
            return uid, 0  # 普通用户

    # API Key
    api_key = request.headers.get("X-API-Key")
    if api_key:
        result = await ApiKeyManager.verify_key(api_key)
        if result:
            uid = result["user_id"]
            async with async_session() as s:
                from backend.models.user import User
                r = await s.execute(select(User).where(User.id == uid))
                u = r.scalar_one_or_none()
                if u and u.is_admin:
                    return uid, 2
            return uid, 1  # API 用户
    raise HTTPException(status_code=401, detail="未登录或缺少 API Key")


@router.post("/tasks")
async def create_task(
    request: Request,
    file: UploadFile = File(...),
    task_type: str = Form("ocr"),
    output_formats: str = Form('["markdown"]'),
):
    """提交 OCR 任务"""
    user_id, priority = await _get_user_id_and_priority(request)

    # 验证文件
    filename = sanitize_filename(file.filename or "unnamed")
    if not is_allowed_file(filename):
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {get_file_extension(filename)}")

    # 分片流式写磁盘，不一次性加载到内存
    settings = get_settings()
    max_bytes = settings.max_file_size_mb * 1024 * 1024
    chunk_size = settings.chunk_size

    task_dir = generate_task_id()
    upload_path = get_upload_path(task_dir)
    file_path = os.path.join(upload_path, filename)

    file_size = 0
    with open(file_path, "wb") as f:
        while True:
            chunk = await file.read(chunk_size)
            if not chunk:
                break
            file_size += len(chunk)
            if file_size > max_bytes:
                # 超限，删掉已写的部分
                f.close()
                os.remove(file_path)
                raise HTTPException(status_code=400, detail=f"文件超过 {settings.max_file_size_mb}MB 限制")
            f.write(chunk)

    # 解析并验证 output_formats
    try:
        formats_list = json.loads(output_formats)
        if not isinstance(formats_list, list):
            raise ValueError
        formats_list = [f for f in formats_list if f in SUPPORTED_FORMATS]
        if not formats_list:
            formats_list = ["markdown"]
    except (json.JSONDecodeError, ValueError):
        formats_list = ["markdown"]
    formats_json = json.dumps(formats_list, ensure_ascii=False)

    # 创建任务记录
    async with async_session() as session:
        task = Task(
            user_id=user_id,
            status="pending",
            task_type=task_type,
            input_filename=filename,
            input_file_path=file_path,
            input_file_size=file_size,
            output_formats=formats_json,
            priority=priority,
        )
        session.add(task)
        await session.commit()
        await session.refresh(task)
        task_id = task.id

    # 加入队列
    await task_engine.enqueue(task_id)

    return {"task_id": task_id, "message": "任务已提交"}


@router.get("/tasks")
async def list_tasks(request: Request, page: int = 1, size: int = 20):
    """获取任务列表"""
    user_id = await _get_user_id(request)
    is_admin = False
    async with async_session() as s:
        from backend.models.user import User
        r = await s.execute(select(User).where(User.id == user_id))
        u = r.scalar_one_or_none()
        if u:
            is_admin = bool(u.is_admin)

    async with async_session() as session:
        query = select(Task).order_by(desc(Task.created_at))
        if not is_admin:
            query = query.where(Task.user_id == user_id)
            # 普通用户不显示软删的
            query = query.where(Task.deleted == 0)
        else:
            # 管理员不显示硬删的
            query = query.where(Task.deleted != 2)
        query = query.offset((page - 1) * size).limit(size)
        result = await session.execute(query)
        tasks = result.scalars().all()
        return {
            "tasks": [
                {
                    "id": t.id,
                    "status": t.status,
                    "task_type": t.task_type,
                    "input_filename": t.input_filename,
                    "input_file_size": t.input_file_size,
                    "progress": t.progress,
                    "page_current": t.page_current,
                    "page_total": t.page_total,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    "output_formats": t.output_formats,
                    "processing_time": t.processing_time,
                }
                for t in tasks
            ]
        }


@router.get("/tasks/{task_id}")
async def get_task(task_id: int, request: Request):
    """获取任务详情"""
    user_id, is_admin = await _get_user_id_and_priority(request)
    is_admin = is_admin == 2
    async with async_session() as session:
        query = select(Task).where(Task.id == task_id)
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        # 读取结果
        result_text = ""
        if task.status == "completed" and task.result_path:
            md_path = os.path.join(task.result_path, "result.md")
            if os.path.exists(md_path):
                with open(md_path, "r", encoding="utf-8") as f:
                    result_text = f.read()

        return {
            "task": {
                "id": task.id,
                "status": task.status,
                "task_type": task.task_type,
                "input_filename": task.input_filename,
                "input_file_size": task.input_file_size,
                "output_formats": task.output_formats,
                "progress": task.progress,
                "page_current": task.page_current,
                "page_total": task.page_total,
                "error_message": task.error_message,
                "created_at": task.created_at.isoformat() if task.created_at else None,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                "processing_time": task.processing_time,
            },
            "result": result_text,
        }


@router.delete("/tasks/{task_id}")
async def cancel_task(task_id: int, request: Request):
    """取消/删除任务"""
    user_id, is_admin = await _get_user_id_and_priority(request)
    is_admin = is_admin == 2
    async with async_session() as session:
        query = select(Task).where(Task.id == task_id)
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")

        if task.status in ("pending", "queued"):
            await session.execute(
                update(Task).where(Task.id == task_id).values(status="cancelled")
            )
            await session.commit()
            return {"message": "任务已取消"}
        elif task.status == "completed":
            return {"message": "任务已完成，无法取消"}
        else:
            return {"message": f"任务当前状态: {task.status}，无法取消"}
