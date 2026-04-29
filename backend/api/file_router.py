import os
import json
import zipfile
import io
import tempfile
from urllib.parse import quote
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, desc, func, or_

from backend.api.ocr_router import _get_user_id
from backend.auth.session import SessionManager
from backend.config import get_settings
from backend.database import async_session
from backend.models.task import Task
from backend.services.export_service import ExportService

router = APIRouter(prefix="/api/v1/files", tags=["文件管理"])


async def _get_user_id_and_role(request: Request) -> tuple[int, bool]:
    """返回 (user_id, is_admin)"""
    settings = get_settings()
    session_mgr = SessionManager()

    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        user = session_mgr.get_session(session_id)
        if user:
            return user["user_id"], bool(user.get("is_admin"))

    from backend.auth.api_key import ApiKeyManager
    api_key = request.headers.get("X-API-Key")
    if api_key:
        result = await ApiKeyManager.verify_key(api_key)
        if result:
            async with async_session() as s:
                from backend.models.user import User
                r = await s.execute(select(User).where(User.id == result["user_id"]))
                u = r.scalar_one_or_none()
                if u:
                    return u.id, bool(u.is_admin)

    raise HTTPException(status_code=401, detail="未登录")


def _get_mime_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".bmp": "image/bmp",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".webp": "image/webp",
    }
    return mime_map.get(ext, "application/octet-stream")


@router.get("")
async def list_files(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    status: str = Query(""),
):
    user_id, is_admin = await _get_user_id_and_role(request)

    async with async_session() as session:
        query = select(Task)
        count_query = select(func.count(Task.id))

        # 管理员硬删的记录不显示
        query = query.where(Task.deleted != 2)
        count_query = count_query.where(Task.deleted != 2)

        if not is_admin:
            query = query.where(Task.user_id == user_id)
            count_query = count_query.where(Task.user_id == user_id)
            # 普通用户不显示自己软删的
            query = query.where(Task.deleted == 0)
            count_query = count_query.where(Task.deleted == 0)

        if search:
            query = query.where(Task.input_filename.ilike(f"%{search}%"))
            count_query = count_query.where(Task.input_filename.ilike(f"%{search}%"))
        if status:
            query = query.where(Task.status == status)
            count_query = count_query.where(Task.status == status)

        total_res = await session.execute(count_query)
        total = total_res.scalar()

        query = query.order_by(desc(Task.created_at)).offset((page - 1) * size).limit(size)
        result = await session.execute(query)
        tasks = result.scalars().all()

        items = []
        for t in tasks:
            item = {
                "id": t.id,
                "filename": t.input_filename,
                "file_size": t.input_file_size,
                "file_type": os.path.splitext(t.input_filename or "")[1].lstrip("."),
                "status": t.status,
                "progress": t.progress,
                "output_formats": t.output_formats,
                "processing_time": t.processing_time,
                "deleted": t.deleted,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            if is_admin:
                item["user_id"] = t.user_id
                # 查用户名
                from backend.models.user import User
                u_result = await session.execute(select(User).where(User.id == t.user_id))
                u = u_result.scalar_one_or_none()
                item["username"] = u.display_name or u.username if u else str(t.user_id)
            items.append(item)

        return {"files": items, "total": total, "page": page, "size": size}


@router.get("/{file_id}/preview")
async def preview_file(file_id: int, request: Request):
    """原文件预览（图片/PDF）"""
    user_id, is_admin = await _get_user_id_and_role(request)
    async with async_session() as session:
        query = select(Task).where(Task.id == file_id)
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if not task or not task.input_file_path or not os.path.exists(task.input_file_path):
            raise HTTPException(status_code=404, detail="文件不存在")

        mime = _get_mime_type(task.input_filename or "")
        return FileResponse(task.input_file_path, media_type=mime)


@router.get("/{file_id}/download")
async def download_file(file_id: int, request: Request, format: str = Query("md")):
    user_id, is_admin = await _get_user_id_and_role(request)

    async with async_session() as session:
        query = select(Task).where(Task.id == file_id)
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="文件不存在")
        if task.status != "completed":
            raise HTTPException(status_code=400, detail="任务未完成")

        md_path = os.path.join(task.result_path, "result.md") if task.result_path else None
        if not md_path or not os.path.exists(md_path):
            raise HTTPException(status_code=404, detail="结果文件不存在")

        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()

        base_name = os.path.splitext(task.input_filename or "result")[0]

        if format == "txt":
            content = ExportService.md_to_txt(md_text)
            return StreamingResponse(
                io.BytesIO(content.encode("utf-8")),
                media_type="text/plain",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(base_name)}.txt"},
            )
        elif format == "json":
            json_path = os.path.join(task.result_path, "result.json") if task.result_path else None
            if json_path and os.path.exists(json_path):
                return FileResponse(
                    json_path,
                    media_type="application/json",
                    filename=f"{base_name}.json",
                )
            # 没有 JSON 文件则降级为简单格式
            content = json.dumps({"markdown": md_text}, ensure_ascii=False, indent=2)
            return StreamingResponse(
                io.BytesIO(content.encode("utf-8")),
                media_type="application/json",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(base_name)}.json"},
            )
        elif format == "docx":
            docx_bytes = ExportService.md_to_docx(md_text)
            return StreamingResponse(
                io.BytesIO(docx_bytes),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(base_name)}.docx"},
            )
        elif format == "zip":
            # 打包结果目录所有文件（源文件 + 图片 + 结果）
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                if task.result_path and os.path.isdir(task.result_path):
                    for root, dirs, files in os.walk(task.result_path):
                        for fname in files:
                            fpath = os.path.join(root, fname)
                            arcname = os.path.relpath(fpath, task.result_path)
                            zf.write(fpath, f"{base_name}/{arcname}")
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(base_name)}.zip"},
            )
        else:
            return FileResponse(
                md_path,
                media_type="text/markdown",
                filename=f"{base_name}.md",
            )


@router.post("/batch-download")
async def batch_download(request: Request):
    body = await request.json()
    file_ids = body.get("file_ids", [])
    fmt = body.get("format", "md")
    if not file_ids:
        raise HTTPException(status_code=400, detail="请选择文件")

    user_id, is_admin = await _get_user_id_and_role(request)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        async with async_session() as session:
            query = select(Task).where(Task.id.in_(file_ids))
            if not is_admin:
                query = query.where(Task.user_id == user_id)
            result = await session.execute(query)
            tasks = result.scalars().all()

            for task in tasks:
                if task.status != "completed" or not task.result_path:
                    continue
                base_name = os.path.splitext(task.input_filename or "result")[0]

                # 打包结果目录中的所有文件（源文件 + 图片 + 结果文件）
                if os.path.isdir(task.result_path):
                    for root, dirs, files in os.walk(task.result_path):
                        for fname in files:
                            fpath = os.path.join(root, fname)
                            arcname = os.path.relpath(fpath, task.result_path)
                            zf.write(fpath, f"{base_name}/{arcname}")

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=ocr_results.zip"},
    )


@router.delete("")
async def delete_all_files(request: Request):
    """全部删除"""
    user_id, is_admin = await _get_user_id_and_role(request)
    import shutil

    async with async_session() as session:
        query = select(Task)
        if not is_admin:
            query = query.where(Task.user_id == user_id).where(Task.deleted == 0)
        else:
            query = query.where(Task.deleted != 2)
        result = await session.execute(query)
        tasks = result.scalars().all()

        deleted = 0
        for task in tasks:
            # 管理员硬删文件
            if is_admin:
                if task.input_file_path and os.path.exists(task.input_file_path):
                    parent = os.path.dirname(task.input_file_path)
                    if os.path.isdir(parent):
                        shutil.rmtree(parent, ignore_errors=True)
                if task.result_path and os.path.exists(task.result_path):
                    shutil.rmtree(task.result_path, ignore_errors=True)
                task.deleted = 2
            else:
                if task.status in ("pending", "queued", "processing"):
                    task.status = "cancelled"
                task.deleted = 1
            deleted += 1

        await session.commit()

    return {"message": f"已删除 {deleted} 条记录", "deleted": deleted}


@router.delete("/{file_id}")
async def delete_file(file_id: int, request: Request):
    user_id, is_admin = await _get_user_id_and_role(request)

    async with async_session() as session:
        query = select(Task).where(Task.id == file_id)
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="文件不存在")

        if is_admin:
            # 管理员：硬删 — 删文件 + 删数据库
            import shutil
            if task.input_file_path and os.path.exists(task.input_file_path):
                parent = os.path.dirname(task.input_file_path)
                if os.path.isdir(parent):
                    shutil.rmtree(parent, ignore_errors=True)
            if task.result_path and os.path.exists(task.result_path):
                shutil.rmtree(task.result_path, ignore_errors=True)
            task.deleted = 2
            await session.commit()
            return {"message": "已彻底删除", "hard_delete": True}
        else:
            # 普通用户：软删 — 只标记，不删文件
            if task.status in ("pending", "queued", "processing"):
                task.status = "cancelled"
            task.deleted = 1
            await session.commit()
            return {"message": "已删除", "hard_delete": False}
