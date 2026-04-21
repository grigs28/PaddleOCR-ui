"""Office 文档处理：docx/xlsx 文本提取 + LibreOffice 转 PDF（可选）"""

import asyncio
import io
import json
import logging
import os
import shutil

from backend.config import get_settings

logger = logging.getLogger(__name__)

# 检测 LibreOffice 是否可用
_libreoffice_path: str | None = None


def _find_libreoffice() -> str | None:
    for cmd in ("libreoffice", "soffice", "/usr/bin/libreoffice", "/usr/bin/soffice"):
        if shutil.which(cmd):
            return cmd
    return None


def is_libreoffice_available() -> bool:
    global _libreoffice_path
    if _libreoffice_path is None:
        _libreoffice_path = _find_libreoffice()
    return _libreoffice_path is not None


async def convert_to_pdf(input_path: str, output_dir: str) -> str | None:
    """
    用 LibreOffice headless 将 Office 文件转 PDF。
    返回 PDF 路径，失败返回 None。
    """
    if not is_libreoffice_available():
        return None

    cmd = [
        _libreoffice_path,
        "--headless",
        "--convert-to", "pdf",
        "--outdir", output_dir,
        input_path,
    ]
    try:
        import tempfile
        # 用临时目录做 user profile，避免多实例锁冲突
        profile_dir = tempfile.mkdtemp(prefix="lo_profile_")
        full_cmd = [_libreoffice_path, f"-env:UserInstallation=file://{profile_dir}"] + cmd[1:]
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=get_settings().libreoffice_timeout)
        if proc.returncode == 0:
            base = os.path.splitext(os.path.basename(input_path))[0]
            pdf_path = os.path.join(output_dir, f"{base}.pdf")
            if os.path.exists(pdf_path):
                return pdf_path
        logger.warning(f"LibreOffice 转换失败: rc={proc.returncode}, stderr={stderr.decode()[:200]}")
    except asyncio.TimeoutError:
        logger.warning("LibreOffice 转换超时(3600s)")
        try:
            proc.kill()
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"LibreOffice 异常: {e}")
    finally:
        # 清理临时 profile
        try:
            import shutil
            shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass
    return None


def is_legacy_office(filename: str) -> bool:
    """doc/xls 旧格式，python 库不支持，必须走 LibreOffice"""
    ext = os.path.splitext(filename)[1].lstrip(".").lower()
    return ext in ("doc", "xls")


def extract_docx_text(file_path: str) -> dict:
    """提取 docx 文本，返回 {markdown, pages, structured}"""
    from docx import Document

    doc = Document(file_path)
    parts = []
    structured_pages = []
    blocks = []
    block_id = 0

    for para in doc.paragraphs:
        style = para.style.name if para.style else ""
        text = para.text.strip()
        if not text:
            continue

        # 根据样式判断类型
        if "Heading 1" in style:
            label = "doc_title"
            md = f"# {text}"
        elif "Heading" in style:
            label = "paragraph_title"
            level = style.replace("Heading ", "").strip()
            try:
                lvl = int(level)
            except ValueError:
                lvl = 2
            md = f"{'#' * min(lvl, 6)} {text}"
        else:
            label = "text"
            md = text

        parts.append(md)
        blocks.append({
            "id": block_id,
            "global_id": block_id,
            "type": label,
            "content": text,
            "bbox": None,
            "order": None,
        })
        block_id += 1

    # 提取表格
    for table in doc.tables:
        rows_data = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows_data.append(cells)

        if rows_data:
            # markdown 表格
            header = "| " + " | ".join(rows_data[0]) + " |"
            sep = "| " + " | ".join(["---"] * len(rows_data[0])) + " |"
            body = "\n".join("| " + " | ".join(r) + " |" for r in rows_data[1:])
            table_md = f"{header}\n{sep}\n{body}"
            parts.append(table_md)
            blocks.append({
                "id": block_id,
                "global_id": block_id,
                "type": "table",
                "content": json.dumps(rows_data, ensure_ascii=False),
                "bbox": None,
                "order": None,
            })
            block_id += 1

    markdown = "\n\n".join(parts)
    structured_pages.append({
        "page": 1,
        "width": None,
        "height": None,
        "blocks": blocks,
    })

    return {
        "markdown": markdown,
        "pages": 1,
        "structured": structured_pages,
    }


def extract_xlsx_text(file_path: str) -> dict:
    """提取 xlsx 文本，返回 {markdown, pages, structured}"""
    from openpyxl import load_workbook

    wb = load_workbook(file_path, read_only=True, data_only=True)
    parts = []
    structured_pages = []
    global_block_id = 0

    for sheet_idx, sheet_name in enumerate(wb.sheetnames):
        ws = wb[sheet_name]
        blocks = []
        rows_data = []

        for row in ws.iter_rows(values_only=True):
            cells = [str(c) if c is not None else "" for c in row]
            # 跳过全空行
            if not any(cells):
                continue
            rows_data.append(cells)

        if not rows_data:
            continue

        # markdown 表格
        header = "| " + " | ".join(rows_data[0]) + " |"
        sep = "| " + " | ".join(["---"] * len(rows_data[0])) + " |"
        body = "\n".join("| " + " | ".join(r) + " |" for r in rows_data[1:])
        table_md = f"## {sheet_name}\n\n{header}\n{sep}\n{body}"

        parts.append(table_md)
        blocks.append({
            "id": 0,
            "global_id": global_block_id,
            "type": "table",
            "content": json.dumps(rows_data, ensure_ascii=False),
            "bbox": None,
            "order": None,
        })
        global_block_id += 1

        structured_pages.append({
            "page": sheet_idx + 1,
            "width": None,
            "height": None,
            "blocks": blocks,
        })

    wb.close()
    markdown = "\n\n".join(parts)

    return {
        "markdown": markdown,
        "pages": len(structured_pages),
        "structured": structured_pages,
    }
