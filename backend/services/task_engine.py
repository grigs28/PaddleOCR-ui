import asyncio
import json
import logging
import os
import shutil
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update

from backend.config import get_settings
from backend.database import async_session
from backend.models.task import Task
from backend.services.ocr_client import ocr_client
from backend.services.progress_estimator import progress_estimator
from backend.services.doc_converter import (
    is_libreoffice_available, convert_to_pdf, is_legacy_office,
    extract_docx_text, extract_xlsx_text,
    is_cad2x_available, convert_dwg_to_pdf,
)
from backend.utils.file_utils import (
    is_image_file, is_pdf_file, is_doc_file, is_cad_file,
    get_file_extension, get_result_path,
)

logger = logging.getLogger(__name__)


class TaskEngine:
    """异步任务引擎 — 优先级队列 + Semaphore 并发控制

    优先级: 2=管理员(最高) > 1=API > 0=普通用户
    数字越大优先级越高，队列中优先弹出。
    """

    def __init__(self):
        settings = get_settings()
        self.image_semaphore = asyncio.Semaphore(settings.image_semaphore_size)
        self.pdf_semaphore = asyncio.Semaphore(settings.pdf_semaphore_size)
        # 优先级队列: (负优先级, 入队序号, task_id) — asyncio.PriorityQueue 弹最小的
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._counter = 0  # 入队序号，同优先级先到先服务
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    async def start(self):
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("任务引擎已启动（3级优先级队列）")

    async def stop(self):
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
        logger.info("任务引擎已停止")

    async def enqueue(self, task_id: int):
        """将任务加入优先级队列"""
        # 查数据库获取 priority
        async with async_session() as s:
            r = await s.execute(select(Task).where(Task.id == task_id))
            t = r.scalar_one_or_none()
            priority = t.priority if t else 0

        self._counter += 1
        # 负优先级：管理员(2) → -2 最先出队，用户(0) → 0 最后出队
        await self._queue.put((-priority, self._counter, task_id))
        await self._update_status(task_id, "queued")
        logger.info(f"任务 {task_id} 入队, priority={priority}, 序号={self._counter}")

    async def _worker(self):
        while self._running:
            try:
                neg_pri, seq, task_id = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            try:
                await self._process_task(task_id)
            except Exception as e:
                logger.error(f"任务 {task_id} 处理异常: {e}")
                await self._update_status(task_id, "failed", error=str(e))

    async def _process_task(self, task_id: int):
        async with async_session() as session:
            result = await session.execute(select(Task).where(Task.id == task_id))
            task = result.scalar_one_or_none()
            if not task:
                logger.error(f"任务 {task_id} 不存在")
                return

            filename = task.input_filename or ""
            file_path = task.input_file_path or ""
            file_size = task.input_file_size or 0

            if not os.path.exists(file_path):
                await self._update_status(task_id, "failed", error="文件不存在")
                return

            if is_pdf_file(filename):
                sem = self.pdf_semaphore
            else:
                sem = self.image_semaphore

            async with sem:
                await self._update_status(task_id, "processing")
                started_at = datetime.now()
                await self._update_field(task_id, "started_at", started_at)
                wall_start = time.monotonic()

                # 判断是否为两阶段任务（Office/CAD 文档需先转 PDF）
                two_phase = is_doc_file(filename) or is_cad_file(filename)
                # 启动进度估算协程
                progress_loop = asyncio.create_task(
                    self._progress_loop(task_id, task.user_id, file_size, wall_start, two_phase)
                )

                try:
                    ext = get_file_extension(filename)
                    ocr_result = None
                    converted_pdf_path = None  # LibreOffice 转换的 PDF 路径

                    # docx/xlsx/doc/xls: 优先尝试 LibreOffice 转 PDF → OCR
                    if is_doc_file(filename):
                        if is_legacy_office(filename) and not is_libreoffice_available():
                            await self._update_status(task_id, "failed", error=f"旧版 .{ext} 格式需要 LibreOffice 支持")
                            progress_loop.cancel()
                            try:
                                await progress_loop
                            except asyncio.CancelledError:
                                pass
                            return

                        if is_libreoffice_available():
                            # 阶段1: 转换 PDF
                            await self._push_progress(task_id, task.user_id, 0, phase="converting")
                            pdf_path = await convert_to_pdf(file_path, os.path.dirname(file_path))
                            converted_pdf_path = pdf_path  # 保留，后面存到结果目录
                            # 标记阶段1完成
                            await self._push_progress(task_id, task.user_id, 50, phase="ocr")
                            if pdf_path:
                                ocr_result = await ocr_client.recognize_pdf(pdf_path)

                        # LibreOffice 不可用或转换失败，直接提取文本
                        if ocr_result is None:
                            if ext == "docx":
                                ocr_result = extract_docx_text(file_path)
                            elif ext == "xlsx":
                                ocr_result = extract_xlsx_text(file_path)
                            else:
                                await self._update_status(task_id, "failed", error=f"不支持的文件类型: {filename}")
                                return

                    elif is_cad_file(filename):
                        # DWG/DXF: cad2x 转 PDF → OCR
                        if not is_cad2x_available():
                            await self._update_status(task_id, "failed", error="DWG/DXF 转换需要 cad2x 工具支持")
                            progress_loop.cancel()
                            try:
                                await progress_loop
                            except asyncio.CancelledError:
                                pass
                            return
                        await self._push_progress(task_id, task.user_id, 0, phase="converting")
                        pdf_path = await convert_dwg_to_pdf(file_path, os.path.dirname(file_path))
                        converted_pdf_path = pdf_path
                        await self._push_progress(task_id, task.user_id, 50, phase="ocr")
                        if pdf_path:
                            ocr_result = await ocr_client.recognize_pdf(pdf_path)
                        else:
                            await self._update_status(task_id, "failed", error="DWG/DXF 转 PDF 失败")
                            progress_loop.cancel()
                            try:
                                await progress_loop
                            except asyncio.CancelledError:
                                pass
                            return

                    elif is_image_file(filename):
                        ocr_result = await ocr_client.recognize_image(file_path)
                    elif is_pdf_file(filename):
                        ocr_result = await ocr_client.recognize_pdf(file_path)
                    else:
                        await self._update_status(task_id, "failed", error=f"不支持的文件类型: {filename}")
                        return

                    # 停止进度估算
                    progress_loop.cancel()
                    try:
                        await progress_loop
                    except asyncio.CancelledError:
                        pass

                    # 保存结果
                    result_dir = get_result_path(str(task_id))
                    md_text = ocr_result["markdown"]
                    md_path = os.path.join(result_dir, "result.md")
                    with open(md_path, "w", encoding="utf-8") as f:
                        f.write(md_text)

                    # 保存 OCR 提取的图片
                    ocr_images = ocr_result.get("images", {})
                    if ocr_images:
                        import base64 as b64mod
                        img_dir = os.path.join(result_dir, "images")
                        os.makedirs(img_dir, exist_ok=True)
                        for img_name, img_b64 in ocr_images.items():
                            img_path = os.path.join(img_dir, img_name)
                            with open(img_path, "wb") as f:
                                f.write(b64mod.b64decode(img_b64))
                        logger.info(f"任务 {task_id} 保存 {len(ocr_images)} 张图片")

                    # 保存源文件到结果目录
                    source_dest = os.path.join(result_dir, f"source_{filename}")
                    shutil.copy2(file_path, source_dest)

                    # Office 文档：保留 LibreOffice 转换的 PDF
                    if converted_pdf_path and os.path.exists(converted_pdf_path):
                        base_name = os.path.splitext(filename)[0]
                        pdf_dest = os.path.join(result_dir, f"{base_name}.pdf")
                        shutil.copy2(converted_pdf_path, pdf_dest)
                        # 清理临时 PDF
                        try:
                            os.remove(converted_pdf_path)
                        except OSError:
                            pass

                    # 按用户选择的格式生成多格式输出
                    output_formats = []
                    try:
                        output_formats = json.loads(task.output_formats or '["markdown"]')
                    except Exception:
                        output_formats = ["markdown"]

                    from backend.services.export_service import ExportService
                    txt_content = None
                    if "txt" in output_formats or "json" in output_formats:
                        txt_content = ExportService.md_to_txt(md_text)
                    if "txt" in output_formats:
                        with open(os.path.join(result_dir, "result.txt"), "w", encoding="utf-8") as f:
                            f.write(txt_content)
                    if "json" in output_formats:
                        with open(os.path.join(result_dir, "result.json"), "w", encoding="utf-8") as f:
                            json.dump({
                                "pages": ocr_result["pages"],
                                "structured_pages": ocr_result.get("structured", []),
                                "markdown": md_text,
                            }, f, ensure_ascii=False, indent=2)
                    if "docx" in output_formats:
                        docx_bytes = ExportService.md_to_docx(md_text)
                        with open(os.path.join(result_dir, "result.docx"), "wb") as f:
                            f.write(docx_bytes)

                    # 计算处理用时
                    processing_seconds = int(time.monotonic() - wall_start)
                    completed_at = datetime.now()

                    # API 任务（priority=1）：完成后自动清理文件和数据库
                    is_api_task = task.priority == 1
                    if is_api_task:
                        # 先更新完成状态（含 result_path），让 API 能读到结果
                        async with async_session() as s:
                            await s.execute(
                                update(Task)
                                .where(Task.id == task_id)
                                .values(
                                    result_path=result_dir,
                                    progress=100,
                                    page_total=ocr_result["pages"],
                                    page_current=ocr_result["pages"],
                                    processing_time=processing_seconds,
                                    completed_at=completed_at,
                                    status="completed",
                                )
                            )
                            await s.commit()
                    else:
                        async with async_session() as s:
                            await s.execute(
                                update(Task)
                                .where(Task.id == task_id)
                                .values(
                                    result_path=result_dir,
                                    progress=100,
                                    page_total=ocr_result["pages"],
                                    page_current=ocr_result["pages"],
                                    processing_time=processing_seconds,
                                    completed_at=completed_at,
                                    status="completed",
                                )
                            )
                            await s.commit()

                    logger.info(f"任务 {task_id} 完成, {ocr_result['pages']}页, {len(md_text)}字符, 用时{processing_seconds}秒")

                    # 推送完成状态到前端
                    try:
                        from backend.ws.progress import progress_manager
                        await progress_manager.send_progress(task.user_id, task_id, {
                            "status": "completed",
                            "progress": 100,
                            "processing_time": processing_seconds,
                        })
                    except Exception:
                        pass

                    # API 任务：延迟清理（给 API 客户端 30 秒读取结果）
                    if is_api_task:
                        asyncio.create_task(self._cleanup_api_task(task_id, result_dir, file_path))

                except Exception as e:
                    progress_loop.cancel()
                    try:
                        await progress_loop
                    except asyncio.CancelledError:
                        pass
                    await self._update_status(task_id, "failed", error=str(e))
                    raise

    async def _progress_loop(self, task_id: int, user_id: int, file_size: int, wall_start: float, two_phase: bool = False):
        """每 5 秒估算进度并推送。two_phase 时: 0-50=转换PDF, 50-100=OCR"""
        try:
            while True:
                await asyncio.sleep(5)
                elapsed = time.monotonic() - wall_start
                raw_progress = await progress_estimator.estimate(file_size, elapsed)
                # 两阶段: 当前阶段用 raw_progress 映射到对应区间
                if two_phase:
                    # 查当前进度判断处于哪个阶段
                    async with async_session() as s:
                        r = await s.execute(select(Task.progress).where(Task.id == task_id))
                        current = r.scalar_one_or_none() or 0
                    if current < 50:
                        # 还在转换 PDF 阶段，raw_progress 映射到 0-45
                        progress = min(int(raw_progress * 0.45), 45)
                    else:
                        # OCR 阶段，raw_progress 映射到 50-95
                        progress = 50 + min(int(raw_progress * 0.45), 45)
                else:
                    progress = raw_progress
                # 更新数据库
                async with async_session() as s:
                    await s.execute(
                        update(Task).where(Task.id == task_id).values(progress=progress)
                    )
                    await s.commit()
                # 推送 WebSocket
                try:
                    from backend.ws.progress import progress_manager
                    await progress_manager.send_progress(user_id, task_id, {
                        "status": "processing",
                        "progress": progress,
                    })
                except Exception:
                    pass
        except asyncio.CancelledError:
            pass

    async def _push_progress(self, task_id: int, user_id: int, progress: int, phase: str = None):
        """主动推送进度（阶段切换时调用）"""
        async with async_session() as s:
            await s.execute(
                update(Task).where(Task.id == task_id).values(progress=progress)
            )
            await s.commit()
        try:
            from backend.ws.progress import progress_manager
            data = {"status": "processing", "progress": progress}
            if phase:
                data["phase"] = phase
            await progress_manager.send_progress(user_id, task_id, data)
        except Exception:
            pass

    async def _cleanup_api_task(self, task_id: int, result_dir: str, input_file_path: str):
        """API 任务延迟 30 秒后清理文件和数据库记录"""
        await asyncio.sleep(30)
        try:
            # 删除文件
            if result_dir and os.path.isdir(result_dir):
                shutil.rmtree(result_dir, ignore_errors=True)
            if input_file_path and os.path.exists(input_file_path):
                parent = os.path.dirname(input_file_path)
                if os.path.isdir(parent):
                    shutil.rmtree(parent, ignore_errors=True)
            # 删除数据库记录
            async with async_session() as s:
                await s.execute(Task.__table__.delete().where(Task.id == task_id))
                await s.commit()
            logger.info(f"API 任务 {task_id} 已自动清理")
        except Exception as e:
            logger.warning(f"API 任务 {task_id} 清理失败: {e}")

    async def _update_status(self, task_id: int, status: str, error: str = None):
        async with async_session() as session:
            values = {"status": status}
            if error:
                values["error_message"] = error[:2000]
            if status == "completed":
                values["completed_at"] = datetime.now()
            await session.execute(update(Task).where(Task.id == task_id).values(**values))
            await session.commit()

        # 推送 WebSocket 进度
        try:
            from backend.ws.progress import progress_manager
            async with async_session() as s:
                r = await s.execute(select(Task).where(Task.id == task_id))
                t = r.scalar_one_or_none()
                if t:
                    await progress_manager.send_progress(t.user_id, task_id, {
                        "status": status,
                        "progress": t.progress if t else 0,
                        "processing_time": t.processing_time,
                        "error": error,
                    })
        except Exception as e:
            logger.warning(f"WebSocket 进度推送失败: {e}")

    async def _update_field(self, task_id: int, field: str, value):
        async with async_session() as session:
            await session.execute(update(Task).where(Task.id == task_id).values({field: value}))
            await session.commit()


# 单例
task_engine = TaskEngine()
