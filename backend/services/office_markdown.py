"""Office 文档直转 Markdown / DOCX。

- DOCX → Markdown：Pandoc（保留标题、列表、表格；失败时回退纯文本）
- DOC → DOCX：LibreOffice headless
- DOC → Markdown：LibreOffice DOC→DOCX → Pandoc

DOCX 有显式结构，直接转 Markdown 比「DOCX→PDF→OCR→Markdown」更准确、更快。
"""

import asyncio
import base64
import logging
import mimetypes
import os
import re
import shutil
import signal
import struct
import subprocess
import tempfile
import zipfile
import zlib

from backend.config import get_settings

logger = logging.getLogger(__name__)

# 同步转换的全局并发上限，避免 HTTP 请求绕过任务队列打满 CPU
_PANDOC_SEMAPHORE = asyncio.Semaphore(2)

# 图片内联上限：单张 20MB，总量 50MB；超出则跳过该图片
_MAX_INLINE_FILE = 20 * 1024 * 1024
_MAX_INLINE_TOTAL = 50 * 1024 * 1024
# DOCX 解压后总大小上限，防止压缩炸弹
_MAX_DOCX_UNCOMPRESSED = 500 * 1024 * 1024
_MAX_ZIP_ENTRIES = 10_000
_MAX_ZIP_CENTRAL_DIR = 10 * 1024 * 1024


class DocxValidationError(ValueError):
    """DOCX 结构或大小校验失败；调用方不应回退到 python-docx 继续解析。"""


def _entry_output_chunks(zf, info, chunk_size: int = 1024 * 1024):
    """按 ZIP 本地头读取原始压缩数据并真正解压，逐块产出实际输出。

    不使用 ZipExtFile.read()：它会按中央目录声明的 file_size 截断，
    攻击者可以伪造声明大小绕过解压计数。
    """
    fp = zf.fp
    fp.seek(info.header_offset)
    header = fp.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise DocxValidationError("无效的 ZIP 本地文件头")

    (sig, version, flags, method, mtime, mdate, crc,
     comp_size, uncomp_size, name_len, extra_len) = struct.unpack(
        "<4sHHHHHIIIHH", header
    )

    if flags & 0x1 or info.flag_bits & 0x1:
        raise DocxValidationError("不支持加密 ZIP")
    if method != info.compress_type:
        raise DocxValidationError("ZIP 本地头与中央目录压缩方法不一致")
    # 数据描述符（flag 0x8）存在时，本地头的 comp_size 可能为 0
    if (flags & 0x8) == 0 and comp_size not in (0, info.compress_size):
        raise DocxValidationError("ZIP 压缩大小不一致")

    data_start = info.header_offset + 30 + name_len + extra_len
    fp.seek(data_start)
    remaining = info.compress_size

    if method == 0:  # stored
        while remaining > 0:
            chunk = fp.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
        return

    if method == 8:  # deflate
        decomp = zlib.decompressobj(-15)
        while remaining > 0:
            chunk = fp.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            while chunk:
                out = decomp.decompress(chunk, chunk_size)
                chunk = decomp.unconsumed_tail
                if out:
                    yield out
        out = decomp.flush()
        if out:
            yield out
        return

    raise DocxValidationError(f"不支持的 ZIP 压缩方法: {method}")


def _check_docx_archive(docx_path: str) -> None:
    """实际解压 DOCX 并计数，拒绝压缩炸弹/异常 ZIP。

    不依赖中央目录声明的 file_size：按本地头读取原始压缩流、用 zlib
    真正解压，累计实际输出并与声明大小比对。该函数是 CPU/IO 操作，
    必须在工作线程中调用，不能阻塞事件循环。
    """
    try:
        with zipfile.ZipFile(docx_path) as zf:
            infos = zf.infolist()
            if len(infos) > _MAX_ZIP_ENTRIES:
                raise DocxValidationError(
                    f"DOCX 条目过多 ({len(infos)}，上限 {_MAX_ZIP_ENTRIES})"
                )
            central = sum(info.compress_size for info in infos)
            if central > _MAX_ZIP_CENTRAL_DIR:
                raise DocxValidationError(
                    f"DOCX 中央目录过大 ({central} bytes)"
                )

            total = 0
            for info in infos:
                if info.is_dir():
                    continue
                entry_total = 0
                for chunk in _entry_output_chunks(zf, info):
                    entry_total += len(chunk)
                    total += len(chunk)
                    if total > _MAX_DOCX_UNCOMPRESSED:
                        raise DocxValidationError(
                            f"DOCX 解压后过大（上限 {_MAX_DOCX_UNCOMPRESSED} bytes）"
                        )
                if entry_total != info.file_size:
                    raise DocxValidationError(
                        f"ZIP 声明大小与实际解压大小不一致: {info.filename}"
                    )
    except DocxValidationError:
        raise
    except Exception as e:
        raise DocxValidationError(f"DOCX 校验失败: {e}")


def _inline_media(md: str, media_dir: str) -> str:
    """把 Pandoc 提取出来的图片改写成 data URI。

    只读取 media_dir 内的文件（realpath 包含检查），并限制单张/总大小，
    防止恶意 DOCX 造成任意文件读取或资源膨胀。
    """
    real_root = os.path.realpath(media_dir)
    total = 0

    def _repl(m):
        nonlocal total
        prefix, src, suffix = m.group(1), m.group(2), m.group(3)
        if not src or src.startswith(("data:", "http://", "https://")):
            return m.group(0)

        candidate = src if os.path.isabs(src) else os.path.join(real_root, src)
        path = os.path.realpath(candidate)
        if not (path == real_root or path.startswith(real_root + os.sep)):
            logger.warning(f"拒绝 media 目录外的图片路径: {src}")
            return ""
        if not os.path.isfile(path):
            # Pandoc 也可能输出 media/xxx 相对路径
            fallback = os.path.realpath(
                os.path.join(real_root, "media", os.path.basename(src))
            )
            if fallback.startswith(real_root + os.sep) and os.path.isfile(fallback):
                path = fallback
            else:
                return ""

        try:
            size = os.path.getsize(path)
        except OSError:
            return ""
        if size > _MAX_INLINE_FILE or total + size > _MAX_INLINE_TOTAL:
            logger.warning(f"跳过过大的内联图片: {path} ({size} bytes)")
            return ""

        with open(path, "rb") as f:
            data = f.read()
        total += len(data)
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        encoded = base64.b64encode(data).decode()
        return f"{prefix}data:{mime};base64,{encoded}{suffix}"

    md = re.sub(r'(<img[^>]*\bsrc=")([^"]*)("[^>]*>)', _repl, md)
    md = re.sub(r'(!\[[^\]]*\]\()([^)]*)(\))', _repl, md)
    return md


def _run_pandoc(docx_path: str, media_dir: str, timeout: int) -> str:
    """同步调用 Pandoc，带硬超时；超时会杀掉整个进程组。"""
    import pypandoc

    pandoc = pypandoc.get_pandoc_path()
    cmd = [
        pandoc,
        docx_path,
        "-f", "docx",
        "-t", "gfm",
        "--wrap=none",
        "--extract-media", media_dir,
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            proc.kill()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()
        proc.communicate()
        raise TimeoutError(f"Pandoc 转换超时 ({timeout}s)")

    if proc.returncode != 0:
        detail = (stderr or "").strip()[-300:]
        raise RuntimeError(f"Pandoc 退出码 {proc.returncode}: {detail}")
    return stdout or ""


async def docx_to_markdown(docx_path: str) -> str:
    """DOCX → GFM Markdown（Pandoc，图片内联为 data URI）。"""
    timeout = get_settings().office_markdown_timeout

    def _convert() -> str:
        # 解压校验在 worker 线程中执行，不阻塞事件循环，且受信号量保护
        _check_docx_archive(docx_path)
        media_dir = tempfile.mkdtemp(prefix="docx_media_")
        try:
            md = _run_pandoc(docx_path, media_dir, timeout)
            return _inline_media(md, media_dir)
        finally:
            shutil.rmtree(media_dir, ignore_errors=True)

    async with _PANDOC_SEMAPHORE:
        try:
            md = await asyncio.wait_for(
                asyncio.to_thread(_convert), timeout=timeout + 10
            )
            if md and md.strip():
                return md
            logger.warning(f"Pandoc 输出为空，回退纯文本: {docx_path}")
        except DocxValidationError:
            # 压缩炸弹/非法 ZIP：禁止回退到 python-docx 继续解析
            raise
        except asyncio.TimeoutError:
            # 解压校验或 Pandoc 超时：不再回退，避免重复解析大文件
            raise
        except Exception as e:
            logger.warning(f"Pandoc DOCX→Markdown 失败，回退纯文本: {e}")

        # 回退：python-docx 提取纯文本（无标题/表格结构）
        # 保持在信号量内，避免回退路径绕过并发限制
        from backend.services.pdf_docx import docx_to_text

        return await asyncio.to_thread(docx_to_text, docx_path)


async def office_to_markdown(file_path: str) -> str:
    """支持 .docx / .doc 的 Markdown 转换。"""
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    if ext == "docx":
        return await docx_to_markdown(file_path)

    if ext == "doc":
        from backend.services.doc_converter import convert_to_docx

        tmp_dir = tempfile.mkdtemp(prefix="doc2md_")
        try:
            docx_path = await convert_to_docx(file_path, tmp_dir)
            if not docx_path:
                raise RuntimeError("DOC→DOCX 转换失败（需要 LibreOffice）")
            return await docx_to_markdown(docx_path)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    raise ValueError(f"不支持的格式: .{ext}")


async def office_to_docx(file_path: str, output_dir: str) -> str | None:
    """将 .doc/.docx/.odt/.rtf 转为 .docx，返回 DOCX 路径。

    .docx 直接复制；其余格式用 LibreOffice 转换。失败返回 None。
    """
    ext = os.path.splitext(file_path)[1].lower().lstrip(".")
    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(file_path))[0]
    dest = os.path.join(output_dir, f"{base}.docx")

    if ext == "docx":
        if os.path.abspath(file_path) != os.path.abspath(dest):
            shutil.copy2(file_path, dest)
        return dest

    if ext in ("doc", "odt", "rtf"):
        from backend.services.doc_converter import convert_to_docx

        return await convert_to_docx(file_path, output_dir)

    return None
