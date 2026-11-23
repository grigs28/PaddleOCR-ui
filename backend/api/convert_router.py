"""文档格式转换 API：DOCX/DOC → Markdown，DOC/DOCX → DOCX。

- `POST /api/v1/convert/markdown`
  - DOCX/DOC：同步转换，直接返回 Markdown
  - PDF：创建异步任务，返回 task_id，轮询 `/api/v1/tasks/{task_id}`
- `POST /api/v1/convert/docx`
  - DOC/DOCX/ODT/RTF：转换并直接返回 DOCX 文件
"""

import asyncio
import os
import shutil

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from backend.api.ocr_router import _get_user_id_and_priority
from backend.config import get_settings
from backend.database import async_session
from backend.models.task import Task
from backend.services.office_markdown import office_to_docx, office_to_markdown
from backend.services.task_engine import task_engine
from backend.utils.file_utils import (
    generate_task_id,
    get_file_extension,
    get_upload_path,
    sanitize_filename,
)

router = APIRouter(prefix="/api/v1/convert", tags=["文档转换"])

_DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# 同步转换接口的并发上限，避免绕过任务队列打满 CPU/LibreOffice
_CONVERT_SEMAPHORE = asyncio.Semaphore(2)


async def _save_upload(file: UploadFile) -> tuple[str, str, int]:
    """分片保存上传文件，返回 (路径, 上传目录, 字节数)。"""
    settings = get_settings()
    filename = sanitize_filename(file.filename or "unnamed")
    upload_dir = get_upload_path(generate_task_id())
    file_path = os.path.join(upload_dir, filename)
    max_bytes = settings.max_file_size_mb * 1024 * 1024

    size = 0
    try:
        with open(file_path, "wb") as f:
            while True:
                chunk = await file.read(settings.chunk_size)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=400,
                        detail=f"文件超过 {settings.max_file_size_mb}MB 限制",
                    )
                f.write(chunk)
    except Exception:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise

    return file_path, upload_dir, size


@router.post("/markdown")
async def convert_to_markdown(
    request: Request,
    file: UploadFile = File(...),
    engine: str = Form("mineru"),
):
    """DOCX/DOC 同步返回 Markdown；PDF 转为异步任务。"""
    user_id, priority = await _get_user_id_and_priority(request)

    filename = sanitize_filename(file.filename or "unnamed")
    ext = get_file_extension(filename)
    if ext not in ("docx", "doc", "pdf"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: .{ext}（支持 docx / doc / pdf）",
        )

    file_path, upload_dir, size = await _save_upload(file)

    if ext == "pdf":
        engine = engine if engine in ("mineru", "vl16", "ppocrv6") else "mineru"
        try:
            async with async_session() as session:
                task = Task(
                    user_id=user_id,
                    status="pending",
                    task_type="convert",
                    input_filename=filename,
                    input_file_path=file_path,
                    input_file_size=size,
                    output_formats='["markdown"]',
                    priority=priority,
                    engine=engine,
                )
                session.add(task)
                await session.commit()
                await session.refresh(task)
                task_id = task.id
            await task_engine.enqueue(task_id)
        except Exception:
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise
        return {
            "task_id": task_id,
            "status": "queued",
            "format": "pdf",
            "engine": engine,
            "poll": f"/api/v1/tasks/{task_id}",
            "message": "PDF 解析为异步任务，请轮询任务结果",
        }

    # DOCX / DOC：同步转换（受并发上限保护）
    try:
        async with _CONVERT_SEMAPHORE:
            markdown = await office_to_markdown(file_path)
        return {
            "markdown": markdown,
            "format": ext,
            "engine": "pandoc",
            "chars": len(markdown),
            "filename": filename,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"转换失败: {e}")
    finally:
        shutil.rmtree(upload_dir, ignore_errors=True)


@router.post("/docx")
async def convert_to_docx(
    request: Request,
    file: UploadFile = File(...),
):
    """将 DOC/DOCX/ODT/RTF 转为 DOCX 并直接返回文件。"""
    await _get_user_id_and_priority(request)

    filename = sanitize_filename(file.filename or "unnamed")
    ext = get_file_extension(filename)
    if ext not in ("doc", "docx", "odt", "rtf"):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: .{ext}（支持 doc / docx / odt / rtf）",
        )

    file_path, upload_dir, _size = await _save_upload(file)
    try:
        out_dir = os.path.join(upload_dir, "out")
        os.makedirs(out_dir, exist_ok=True)
        async with _CONVERT_SEMAPHORE:
            docx_path = await office_to_docx(file_path, out_dir)
        if not docx_path or not os.path.isfile(docx_path):
            raise HTTPException(
                status_code=500,
                detail="DOC→DOCX 转换失败（需要 LibreOffice）",
            )
        base_name = os.path.splitext(filename)[0]
        # 流式返回，响应结束后再清理临时目录
        return FileResponse(
            docx_path,
            media_type=_DOCX_MIME,
            filename=f"{base_name}.docx",
            background=BackgroundTask(shutil.rmtree, upload_dir, ignore_errors=True),
        )
    except HTTPException:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise
    except Exception as e:
        shutil.rmtree(upload_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"转换失败: {e}")
