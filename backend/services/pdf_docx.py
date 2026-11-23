"""非图片型 PDF 直转 DOCX（exactdoc）。

路由规则：
- 有文本层的 PDF → exactdoc 直转，保留原版式、图片、页眉页脚和活动页码
- 图片型 PDF（无文本层）→ 调用方继续走 OCR → Markdown → DOCX
- exactdoc 不可用/失败/超时 → 回退 Markdown → DOCX，保证任务不失败

exactdoc 是同步命令行工具，这里用可杀死的子进程调用，超时会连同
LibreOffice 子进程一起清理，避免线程无法取消的问题。
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from typing import Optional

logger = logging.getLogger(__name__)


def has_text_layer(pdf_path: str, max_pages: int = 5, min_chars: int = 50) -> bool:
    """检测 PDF 是否含可提取文本层（只抽查前 max_pages 页）。

    只看前几页，避免大文件解析过慢；min_chars 用于过滤只有页码/水印的页面。
    """
    if not os.path.isfile(pdf_path):
        return False
    try:
        import pypdf

        reader = pypdf.PdfReader(pdf_path)
        pages = reader.pages[:max_pages] if max_pages > 0 else reader.pages
        total = 0
        for page in pages:
            try:
                total += len((page.extract_text() or "").strip())
            except Exception:
                continue
            if total >= min_chars:
                return True
        return total >= min_chars
    except Exception as e:
        logger.warning(f"PDF 文本层检测失败 {pdf_path}: {e}")
        return False


def _run_exactdoc(
    pdf_path: str,
    out_path: str,
    refine_rounds: int,
    max_pages: Optional[int],
    timeout_seconds: int,
) -> None:
    """同步调用 exactdoc CLI。超时/异常会杀掉整个进程组。"""
    cmd = [
        sys.executable, "-m", "exactdoc.cli",
        pdf_path,
        "-o", out_path,
        "--refine", str(refine_rounds),
        "--oracle", "libreoffice",
        "--output-profile", "standard",
    ]
    if max_pages is not None:
        cmd += ["--max-pages", str(max_pages)]

    if os.path.exists(out_path):
        try:
            os.remove(out_path)
        except OSError:
            pass

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            proc.kill()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except OSError:
                proc.kill()
        proc.communicate()
        raise TimeoutError(f"exactdoc 转换超时 ({timeout_seconds}s)")

    if proc.returncode != 0:
        detail = (stderr or stdout or "").strip()[-500:]
        raise RuntimeError(f"exactdoc 退出码 {proc.returncode}: {detail}")

    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise RuntimeError("exactdoc 未生成有效的 DOCX")


async def _convert_to_docx(
    pdf_path: str,
    out_path: str,
    refine_rounds: int,
    max_pages: Optional[int],
    timeout_seconds: int,
) -> None:
    await asyncio.to_thread(
        _run_exactdoc, pdf_path, out_path, refine_rounds, max_pages, timeout_seconds
    )


async def try_exactdoc(
    pdf_path: str,
    out_path: str,
    *,
    min_chars: int = 50,
    refine_rounds: int = 3,
    max_pages: Optional[int] = None,
    timeout_seconds: int = 1800,
) -> bool:
    """尝试 exactdoc 直转；无文本层或转换失败返回 False（不抛异常）。"""
    if not os.path.isfile(pdf_path):
        return False
    if not await asyncio.to_thread(has_text_layer, pdf_path, 5, min_chars):
        logger.info(f"PDF 无文本层，跳过 exactdoc: {os.path.basename(pdf_path)}")
        return False
    try:
        await _convert_to_docx(
            pdf_path, out_path, refine_rounds, max_pages, timeout_seconds
        )
        logger.info(
            f"exactdoc 直转成功: {os.path.basename(pdf_path)} "
            f"(refine={refine_rounds}, max_pages={max_pages})"
        )
        return True
    except Exception as e:
        logger.warning(f"exactdoc 直转失败: {e}")
        return False


def docx_to_text(docx_path: str, max_chars: int = 200_000) -> str:
    """从 DOCX 提取纯文本，供任务预览/result.md 使用（不保证版式）。"""
    try:
        from docx import Document

        doc = Document(docx_path)
        parts: list[str] = []
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if text:
                parts.append(text)
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells]
                if any(cells):
                    parts.append("\t".join(cells))
        return "\n".join(parts)[:max_chars]
    except Exception as e:
        logger.warning(f"DOCX 文本提取失败 {docx_path}: {e}")
        return ""


async def generate_docx(
    pdf_path: str,
    out_path: str,
    md_text: str,
    *,
    enabled: bool = True,
    min_chars: int = 50,
    refine_rounds: int = 3,
    max_pages: Optional[int] = None,
    timeout_seconds: int = 1800,
) -> str:
    """生成 DOCX，返回实际使用的路径：``exactdoc`` 或 ``markdown``。

    仅当 enabled=True 且 PDF 有文本层时尝试 exactdoc；其余情况（图片型
    PDF、exactdoc 未安装、超时、页数超限、转换失败）回退到原有的
    Markdown → DOCX，保证任务仍然完成。
    """
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    if enabled and await try_exactdoc(
        pdf_path,
        out_path,
        min_chars=min_chars,
        refine_rounds=refine_rounds,
        max_pages=max_pages,
        timeout_seconds=timeout_seconds,
    ):
        return "exactdoc"

    # 回退：原有的 Markdown → DOCX
    from backend.services.export_service import ExportService

    data = ExportService.md_to_docx(md_text)
    with open(out_path, "wb") as f:
        f.write(data)
    return "markdown"
