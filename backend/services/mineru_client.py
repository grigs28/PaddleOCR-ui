"""MinerU 客户端 — ACADxPDF 式异步三步 + 队列保障 + 全量保留结果

流程：保障队列 running → 提交 upload_with_progress → 轮询 /api/task/{id}
      → 下载 /api/download_zip?task_id= → 解压全保留到 result_path

MinerU 返回 ZIP（含 md / layout.pdf / origin.pdf / content_list.json / images/），
全部保留到任务结果目录，markdown 文本从 ZIP 内 *.md 读取用于前端展示。
"""

import asyncio
import logging
import os
import zipfile

import aiohttp

from backend.config import get_settings

logger = logging.getLogger(__name__)


async def _ensure_queue_running(client: aiohttp.ClientSession, base: str):
    """确保 MinerU 队列处于 running（默认可能 idle，提交后不处理）"""
    try:
        async with client.get(f"{base}/api/queue/status", timeout=aiohttp.ClientTimeout(total=10)) as r:
            data = await r.json()
        if data.get("queue_status") != "running":
            async with client.post(f"{base}/api/queue/start", timeout=aiohttp.ClientTimeout(total=10)) as r:
                logger.info(f"MinerU 队列已启动: {await r.text()}")
    except Exception as e:
        logger.warning(f"MinerU 队列状态检查失败: {e}")


async def _poll_task(client: aiohttp.ClientSession, base: str, task_id: str, timeout: int = 3600) -> dict:
    """轮询任务状态直到 completed/failed，返回任务数据"""
    deadline = asyncio.get_event_loop().time() + timeout
    last_progress = -1
    while asyncio.get_event_loop().time() < deadline:
        try:
            async with client.get(f"{base}/api/task/{task_id}", timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status != 200:
                    logger.warning(f"MinerU 轮询非200: {r.status}")
                    await asyncio.sleep(5)
                    continue
                data = await r.json()
            status = data.get("status")
            progress = data.get("progress", 0)
            if progress != last_progress:
                logger.info(f"MinerU 任务 {task_id}: {status} {progress}%")
                last_progress = progress
            if status == "completed":
                return data
            if status == "failed":
                raise Exception(f"MinerU 任务失败: {data.get('error_message') or data.get('message')}")
        except Exception as e:
            if "MinerU 任务失败" in str(e):
                raise
            logger.warning(f"MinerU 轮询异常: {e}")
        await asyncio.sleep(5)
    raise Exception(f"MinerU 轮询超时 ({timeout}s)")


async def process_mineru(file_path: str, result_dir: str) -> dict:
    """提交文件到 MinerU，处理完成后下载 ZIP 解压全保留。

    Returns:
        {"markdown": str, "pages": int, "structured": [], "images": {}}
    """
    settings = get_settings()
    base = settings.mineru_service_url.rstrip("/")
    filename = os.path.basename(file_path)

    async with aiohttp.ClientSession() as client:
        # 1. 队列保障
        await _ensure_queue_running(client, base)

        # 2. 提交
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            data.add_field("files", f, filename=filename)
            async with client.post(
                f"{base}/api/upload_with_progress",
                data=data,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    raise Exception(f"MinerU 提交失败 {resp.status}: {(await resp.text())[:200]}")
                submit = await resp.json()
        task_ids = submit.get("task_ids", [])
        if not task_ids:
            raise Exception(f"MinerU 未返回 task_id: {submit}")
        task_id = task_ids[0]
        logger.info(f"MinerU 任务已提交: {task_id} ({filename})")

        # 3. 轮询
        task_data = await _poll_task(client, base, task_id)

        # 4. 下载 ZIP
        async with client.get(
            f"{base}/api/download_zip",
            params={"task_id": task_id},
            timeout=aiohttp.ClientTimeout(total=600),
        ) as resp:
            if resp.status != 200:
                raise Exception(f"MinerU 下载失败 {resp.status}")
            zip_bytes = await resp.read()
        if not zip_bytes:
            raise Exception("MinerU 下载结果为空")

    # 5. 解压全保留到 result_dir
    import io
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        zf.extractall(result_dir)

    # 找 markdown 文件（ZIP 内 <产物>/vlm/*.md）
    md_text = ""
    pages = 1
    for root, dirs, files in os.walk(result_dir):
        for f in files:
            if f.lower().endswith(".md"):
                with open(os.path.join(root, f), "r", encoding="utf-8") as mf:
                    md_text = mf.read()
                break
        if md_text:
            break

    logger.info(f"MinerU 完成: {len(md_text)}字符, 结果目录 {result_dir}")
    return {
        "markdown": md_text,
        "pages": pages,
        "structured": [],
        "images": {},
    }
