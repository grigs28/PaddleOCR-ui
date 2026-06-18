import asyncio
import json
import logging
import os
import re
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
    extract_dxf_text, convert_pdf_to_dwg,
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
        self.acad_semaphore = asyncio.Semaphore(settings.acad_concurrency)
        # 优先级队列: (负优先级, 入队序号, task_id) — asyncio.PriorityQueue 弹最小的
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._counter = 0  # 入队序号，同优先级先到先服务
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None

    def refresh_semaphores(self):
        """热更新并发数（管理面板修改后调用）"""
        settings = get_settings()
        self.image_semaphore = asyncio.Semaphore(settings.image_semaphore_size)
        self.pdf_semaphore = asyncio.Semaphore(settings.pdf_semaphore_size)
        self.acad_semaphore = asyncio.Semaphore(settings.acad_concurrency)
        logger.info(f"信号量已刷新: image={settings.image_semaphore_size}, pdf={settings.pdf_semaphore_size}, acad={settings.acad_concurrency}")

    async def start(self):
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        # 恢复上次重启时未完成的任务
        await self._recover_stuck_tasks()
        logger.info("任务引擎已启动（3级优先级队列）")

    async def _recover_stuck_tasks(self):
        """启动时将未完成的任务重新入队"""
        async with async_session() as s:
            r = await s.execute(
                select(Task).where(Task.status.in_(["processing", "queued", "pending"]))
            )
            tasks = r.scalars().all()
            if not tasks:
                return
            for t in tasks:
                t.status = "pending"
                self._counter += 1
                await self._queue.put((-t.priority, self._counter, t.id))
            await s.commit()
            logger.info(f"已恢复 {len(tasks)} 个未完成任务")

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

            # 并发派发，由 semaphore 控制实际并发数
            asyncio.create_task(self._process_task_safe(task_id))

    async def _process_task_safe(self, task_id: int):
        """包装 _process_task，捕获异常"""
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
            high_precision = bool(task.high_precision)
            engine = task.engine or "vl16"

            if not os.path.exists(file_path):
                await self._update_status(task_id, "failed", error="文件不存在")
                return

            # 判断是否为 ACAD 转换任务（不占用信号量，ACAD 服务自己管理并发）
            output_formats = []
            try:
                output_formats = json.loads(task.output_formats or '["markdown"]')
            except Exception:
                output_formats = ["markdown"]
            is_acad_task = is_cad_file(filename) or (is_pdf_file(filename) and 'dwg' in output_formats)

            if is_acad_task:
                sem = self.acad_semaphore  # ACAD 独立信号量，最多 12 并发
            elif is_pdf_file(filename):
                sem = self.pdf_semaphore
            else:
                sem = self.image_semaphore

            # 非 VL 引擎（PP-OCRv6 / MinerU）走独立处理流程
            if engine in ("ppocrv6", "mineru"):
                async with sem:
                    await self._process_engine_task(task_id, task.user_id, filename, file_path, engine)
                return

            async def _run_with_sem():
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
                    dxf_source_path = None     # DXF 文件路径（CAD 文件用）

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
                                ocr_result = await ocr_client.recognize_pdf(pdf_path, high_precision=high_precision)

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
                        # DWG/DXF: ACAD 转 PDF+DXF
                        await self._push_progress(task_id, task.user_id, 0, phase="converting")
                        pdf_paths = await convert_dwg_to_pdf(file_path, os.path.dirname(file_path), merge=bool(task.merge_pdf))
                        converted_pdf_path = pdf_paths  # list[str]，后面统一处理复制

                        # 查找 DXF 文件（ACAD 服务会在同一目录生成）
                        dxf_path = None
                        output_dir = os.path.dirname(file_path)
                        for f in os.listdir(output_dir):
                            if f.lower().endswith('.dxf'):
                                dxf_path = os.path.join(output_dir, f)
                                break
                        if dxf_path:
                            dxf_source_path = dxf_path

                        # 判断是否需要文字识别
                        text_formats = [f for f in output_formats if f != 'dwg']
                        if not text_formats or not pdf_paths:
                            # 无文字格式 或 转换失败 → 仅保存 PDF，不走 OCR
                            if not pdf_paths:
                                await self._update_status(task_id, "failed", error="DWG/DXF 转换失败")
                                progress_loop.cancel()
                                try:
                                    await progress_loop
                                except asyncio.CancelledError:
                                    pass
                                return
                            # 构造空的 ocr_result，仅用于保存 PDF
                            ocr_result = {"markdown": "", "pages": 1, "images": {}}
                        else:
                            # 有文字格式 → 逐个 OCR 所有 PDF，合并结果
                            # merge=True 时 convert_dwg_to_pdf 已合并为 1 个 PDF
                            # merge=False 时返回多个 PDF，每个都 OCR
                            await self._push_progress(task_id, task.user_id, 80, phase="ocr")
                            all_md, total_pages, all_images, all_structured = [], 0, {}, []
                            for pi, pdf_p in enumerate(pdf_paths):
                                logger.info(f"任务 {task_id} OCR PDF [{pi+1}/{len(pdf_paths)}]: {os.path.basename(pdf_p)}")
                                r = await ocr_client.recognize_pdf(pdf_p, high_precision=high_precision)
                                if r["markdown"]:
                                    all_md.append(r["markdown"])
                                total_pages += r.get("pages", 1)
                                all_images.update(r.get("images", {}))
                                all_structured.extend(r.get("structured", []))
                            ocr_result = {
                                "markdown": "\n\n".join(all_md),
                                "pages": total_pages,
                                "images": all_images,
                                "structured": all_structured,
                            }

                    elif is_image_file(filename):
                        ocr_result = await ocr_client.recognize_image(file_path, high_precision=high_precision)
                    elif is_pdf_file(filename):
                        # PDF: 根据 output_formats 判断走 OCR 还是转 DWG
                        pdf_formats = []
                        try:
                            pdf_formats = json.loads(task.output_formats or '["markdown"]')
                        except Exception:
                            pdf_formats = ["markdown"]

                        if 'dwg' in pdf_formats:
                            # PDF→DWG 纯转换
                            dwg_path = await convert_pdf_to_dwg(file_path, os.path.dirname(file_path))
                            if not dwg_path:
                                await self._update_status(task_id, "failed", error="PDF→DWG 转换失败")
                                return

                            # 直接保存 DWG 结果，不走 OCR
                            progress_loop.cancel()
                            try:
                                await progress_loop
                            except asyncio.CancelledError:
                                pass

                            result_dir = get_result_path(str(task_id))
                            source_dest = os.path.join(result_dir, f"source_{filename}")
                            shutil.copy2(file_path, source_dest)
                            dwg_dest = os.path.join(result_dir, os.path.basename(dwg_path))
                            shutil.copy2(dwg_path, dwg_dest)

                            processing_seconds = int(time.monotonic() - wall_start)
                            completed_at = datetime.now()
                            async with async_session() as s:
                                await s.execute(
                                    update(Task)
                                    .where(Task.id == task_id)
                                    .values(
                                        result_path=result_dir,
                                        progress=100,
                                        page_total=1,
                                        page_current=1,
                                        processing_time=processing_seconds,
                                        completed_at=completed_at,
                                        status="completed",
                                    )
                                )
                                await s.commit()
                            logger.info(f"任务 {task_id} PDF→DWG 完成, 用时{processing_seconds}秒")

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
                            return
                        else:
                            ocr_result = await ocr_client.recognize_pdf(file_path, high_precision=high_precision)
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
                    # 清理 VL 返回的 <table border=1> — 去掉 3D 凸起效果，让前端 CSS 接管
                    md_text = re.sub(r'<table\s+border\s*=\s*["\']?1["\']?', '<table', md_text)
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

                    # CAD 文件：保留 DXF 源文件 + 提取文字到结果目录
                    if dxf_source_path and os.path.exists(dxf_source_path):
                        dxf_dest = os.path.join(result_dir, os.path.basename(dxf_source_path))
                        shutil.copy2(dxf_source_path, dxf_dest)
                        # DXF 文字提取结果单独保存为 _dxf.md
                        base = os.path.splitext(filename)[0]
                        dxf_text = extract_dxf_text(dxf_source_path)
                        if dxf_text and dxf_text.get("markdown"):
                            dxf_md_path = os.path.join(result_dir, f"{base}_dxf.md")
                            with open(dxf_md_path, "w", encoding="utf-8") as f:
                                f.write(dxf_text["markdown"])
                            logger.info(f"任务 {task_id} DXF 文字已保存: {len(dxf_text['markdown'])} 字符")

                    # Office 文档：保留 LibreOffice 转换的 PDF
                    if isinstance(converted_pdf_path, list):
                        # CAD 文件：复制所有 PDF 到结果目录
                        for pdf_p in converted_pdf_path:
                            if os.path.exists(pdf_p):
                                pdf_dest = os.path.join(result_dir, os.path.basename(pdf_p))
                                shutil.copy2(pdf_p, pdf_dest)
                                try:
                                    os.remove(pdf_p)
                                except OSError:
                                    pass
                    elif converted_pdf_path and os.path.exists(converted_pdf_path):
                        base_name = os.path.splitext(filename)[0]
                        pdf_dest = os.path.join(result_dir, f"{base_name}.pdf")
                        shutil.copy2(converted_pdf_path, pdf_dest)
                        # 清理临时 PDF
                        try:
                            os.remove(converted_pdf_path)
                        except OSError:
                            pass

                    # 按用户选择的格式生成多格式输出
                    save_formats = []
                    try:
                        save_formats = json.loads(task.output_formats or '["markdown"]')
                    except Exception:
                        save_formats = ["markdown"]

                    from backend.services.export_service import ExportService
                    txt_content = None
                    if "txt" in save_formats or "json" in save_formats:
                        txt_content = ExportService.md_to_txt(md_text)
                    if "txt" in save_formats:
                        with open(os.path.join(result_dir, "result.txt"), "w", encoding="utf-8") as f:
                            f.write(txt_content)
                    if "json" in save_formats:
                        with open(os.path.join(result_dir, "result.json"), "w", encoding="utf-8") as f:
                            json.dump({
                                "pages": ocr_result["pages"],
                                "structured_pages": ocr_result.get("structured", []),
                                "markdown": md_text,
                            }, f, ensure_ascii=False, indent=2)
                    if "docx" in save_formats:
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

            if sem:
                async with sem:
                    await _run_with_sem()
            else:
                await _run_with_sem()

    async def _process_engine_task(self, task_id: int, user_id: int, filename: str, file_path: str, engine: str):
        """PP-OCRv6 / MinerU 引擎处理流程（独立于 VL 流程）

        Office/CAD 先转 PDF，再送引擎。MinerU 结果全量解压到 result_dir。
        """
        import shutil
        from backend.utils.file_utils import (
            get_result_path, is_pdf_file, is_image_file, is_doc_file, is_cad_file,
        )
        from backend.services.doc_converter import (
            convert_to_pdf, convert_dwg_to_pdf, is_libreoffice_available,
        )

        await self._update_status(task_id, "processing")
        started_at = datetime.now()
        await self._update_field(task_id, "started_at", started_at)
        wall_start = time.monotonic()

        try:
            work_path = file_path
            is_pdf = is_pdf_file(filename)
            is_img = is_image_file(filename)

            # 非 PDF/图片先转 PDF（Office 走 LibreOffice，CAD 走 ACAD）
            if not (is_pdf or is_img):
                if is_doc_file(filename) and is_libreoffice_available():
                    pdf_path = await convert_to_pdf(file_path, os.path.dirname(file_path))
                    if pdf_path:
                        work_path = pdf_path
                        is_pdf = True
                elif is_cad_file(filename):
                    pdfs = await convert_dwg_to_pdf(file_path, os.path.dirname(file_path), merge=True)
                    if pdfs:
                        work_path = pdfs[0]
                        is_pdf = True
                if not is_pdf and not is_img:
                    await self._update_status(task_id, "failed", error=f"引擎 {engine} 仅支持 PDF/图片（及可转 PDF 的文档）: {filename}")
                    return

            await self._push_progress(task_id, user_id, 10)

            # 调引擎
            result_dir = get_result_path(str(task_id))
            if engine == "ppocrv6":
                ocr_result = await ocr_client.recognize_ppocrv6(work_path, is_pdf)
            else:  # mineru
                from backend.services.mineru_client import process_mineru
                ocr_result = await process_mineru(work_path, result_dir)

            await self._push_progress(task_id, user_id, 90)

            # 保存 markdown（MinerU 已解压全量结果到 result_dir，这里统一写 result.md 供前端读取）
            md_text = ocr_result["markdown"]
            with open(os.path.join(result_dir, "result.md"), "w", encoding="utf-8") as f:
                f.write(md_text)

            # PP-OCRv6 保存原始坐标数据（供前端可视化文字层渲染）
            if engine == "ppocrv6" and "ocr_raw" in ocr_result:
                with open(os.path.join(result_dir, "ppocrv6_data.json"), "w", encoding="utf-8") as f:
                    json.dump(ocr_result["ocr_raw"], f, ensure_ascii=False, indent=2)

            # 多格式输出（txt/json/docx），复用 ExportService
            try:
                async with async_session() as s:
                    t = (await s.execute(select(Task).where(Task.id == task_id))).scalar_one_or_none()
                    save_formats = json.loads(t.output_formats or '["markdown"]') if t else ["markdown"]
            except Exception:
                save_formats = ["markdown"]

            from backend.services.export_service import ExportService

            if "txt" in save_formats:
                txt_content = ExportService.md_to_txt(md_text)
                with open(os.path.join(result_dir, "result.txt"), "w", encoding="utf-8") as f:
                    f.write(txt_content)
            if "json" in save_formats:
                with open(os.path.join(result_dir, "result.json"), "w", encoding="utf-8") as f:
                    json.dump({"pages": ocr_result["pages"], "markdown": md_text}, f, ensure_ascii=False, indent=2)
            if "docx" in save_formats:
                docx_bytes = ExportService.md_to_docx(md_text)
                with open(os.path.join(result_dir, "result.docx"), "wb") as f:
                    f.write(docx_bytes)

            # 保留源文件
            source_dest = os.path.join(result_dir, f"source_{filename}")
            shutil.copy2(file_path, source_dest)

            # 清理转换产生的临时 PDF（非源文件）
            if work_path != file_path and os.path.exists(work_path):
                try:
                    os.remove(work_path)
                except OSError:
                    pass

            processing_seconds = int(time.monotonic() - wall_start)
            completed_at = datetime.now()
            async with async_session() as s:
                await s.execute(
                    update(Task).where(Task.id == task_id).values(
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

            logger.info(f"任务 {task_id} [{engine}] 完成, {len(md_text)}字符, {processing_seconds}秒")

            try:
                from backend.ws.progress import progress_manager
                await progress_manager.send_progress(user_id, task_id, {
                    "status": "completed", "progress": 100, "processing_time": processing_seconds,
                })
            except Exception:
                pass

        except Exception as e:
            logger.error(f"任务 {task_id} [{engine}] 异常: {e}")
            await self._update_status(task_id, "failed", error=str(e))

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
