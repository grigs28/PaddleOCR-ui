"""Office 文档直转 Markdown / DOCX。

- DOCX → Markdown：Pandoc（保留标题、列表、表格；失败时回退纯文本）
- DOC → DOCX：LibreOffice headless
- DOC → Markdown：LibreOffice DOC→DOCX → Pandoc

DOCX 有显式结构，直接转 Markdown 比「DOCX→PDF→OCR→Markdown」更准确、更快。
"""

import asyncio
import logging
import os
import shutil
import tempfile

logger = logging.getLogger(__name__)


def _inline_media(md: str, media_dir: str) -> str:
    """把 Pandoc 提取出来的图片改写成 data URI，保证 Markdown 自包含。"""
    import base64
    import mimetypes
    import re

    def _repl(m):
        prefix, src, suffix = m.group(1), m.group(2), m.group(3)
        path = src
        if not os.path.isabs(path):
            path = os.path.join(media_dir, path)
        if not os.path.isfile(path):
            candidate = os.path.join(media_dir, "media", os.path.basename(src))
            if os.path.isfile(candidate):
                path = candidate
        if not os.path.isfile(path):
            return m.group(0)
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        return f"{prefix}data:{mime};base64,{encoded}{suffix}"

    md = re.sub(r'(<img[^>]*\bsrc=")([^"]*)(")', _repl, md)
    md = re.sub(r'(!\[[^\]]*\]\()([^)]*)(\))', _repl, md)
    return md


async def docx_to_markdown(docx_path: str) -> str:
    """DOCX → GFM Markdown（Pandoc，图片内联为 data URI）。"""

    def _convert() -> str:
        import pypandoc
        import shutil
        import tempfile

        media_dir = tempfile.mkdtemp(prefix="docx_media_")
        try:
            md = pypandoc.convert_file(
                docx_path,
                "gfm",
                format="docx",
                extra_args=["--wrap=none", "--extract-media", media_dir],
            )
            return _inline_media(md, media_dir)
        finally:
            shutil.rmtree(media_dir, ignore_errors=True)

    try:
        md = await asyncio.to_thread(_convert)
        if md and md.strip():
            return md
        logger.warning(f"Pandoc 输出为空，回退纯文本: {docx_path}")
    except Exception as e:
        logger.warning(f"Pandoc DOCX→Markdown 失败，回退纯文本: {e}")

    # 回退：python-docx 提取纯文本（无标题/表格结构）
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
