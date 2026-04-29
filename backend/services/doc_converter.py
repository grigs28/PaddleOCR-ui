"""Office 文档处理：docx/xlsx 文本提取 + LibreOffice 转 PDF（可选）+ cad2x DWG 转 PDF"""

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

# 检测 cad2x 是否可用
_cad2x_path: str | None = None


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


def _find_cad2x() -> str | None:
    """查找 cad2x 二进制"""
    # 项目 bin 目录优先
    project_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "bin", "cad2x")
    if os.path.isfile(project_bin) and os.access(project_bin, os.X_OK):
        return project_bin
    # 系统 PATH
    path = shutil.which("cad2x")
    if path:
        return path
    return None


def is_cad2x_available() -> bool:
    global _cad2x_path
    if _cad2x_path is None:
        _cad2x_path = _find_cad2x()
    return _cad2x_path is not None


async def convert_dwg_to_pdf(input_path: str, output_dir: str) -> str | None:
    """DWG/DXF 转 PDF。优先用 ACAD 服务（按图框分页），回退到 cad2x。

    ACAD 服务可能返回多个 PDF（每个图框一个），合并为一个 PDF 返回。
    返回最终 PDF 路径，失败返回 None。
    """
    # 优先尝试 ACAD 服务
    pdf_path = await _convert_dwg_via_acad(input_path, output_dir)
    if pdf_path:
        return pdf_path

    # 回退到 cad2x
    logger.info("ACAD 服务不可用或失败，回退到 cad2x")
    return await _convert_dwg_via_cad2x(input_path, output_dir)


async def _convert_dwg_via_acad(input_path: str, output_dir: str) -> str | None:
    """通过 ACADxPDF 服务将 DWG 转 PDF。返回合并后的 PDF 路径。"""
    import aiohttp
    import zipfile

    settings = get_settings()
    acad_url = settings.acad_service_url.rstrip("/")

    # 先检查服务是否可用
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(f"{acad_url}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status != 200:
                    return None
    except Exception:
        return None

    # 调用转换接口
    try:
        import aiohttp
        async with aiohttp.ClientSession() as client:
            with open(input_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("files", f, filename=os.path.basename(input_path))
                async with client.post(
                    f"{acad_url}/convert",
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=settings.libreoffice_timeout),
                ) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning(f"ACAD 服务返回 {resp.status}: {text[:200]}")
                        return None
                    zip_bytes = await resp.read()
    except Exception as e:
        logger.warning(f"ACAD 服务请求失败: {e}")
        return None

    if not zip_bytes:
        return None

    # 解压 ZIP，收集 PDF 和 DXF
    base = os.path.splitext(os.path.basename(input_path))[0]
    pdf_files = []
    dxf_files = []
    temp_extract = os.path.join(output_dir, f"_acad_temp_{base}")
    os.makedirs(temp_extract, exist_ok=True)

    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(temp_extract)

        for fname in sorted(os.listdir(temp_extract)):
            lower = fname.lower()
            if lower.endswith(".pdf"):
                pdf_files.append(os.path.join(temp_extract, fname))
            elif lower.endswith(".dxf"):
                dxf_files.append(os.path.join(temp_extract, fname))

        if not pdf_files:
            logger.warning("ACAD 返回 ZIP 中无 PDF 文件")
            shutil.rmtree(temp_extract, ignore_errors=True)
            return None

        # 保存 DXF 到输出目录
        for dxf in dxf_files:
            dxf_dest = os.path.join(output_dir, os.path.basename(dxf))
            if not os.path.exists(dxf_dest):
                shutil.move(dxf, dxf_dest)
                logger.info(f"DXF 已保存: {dxf_dest}")

        # 保存单独的图框 PDF 到输出目录
        saved_pdfs = []
        for i, pdf in enumerate(pdf_files):
            page_dest = os.path.join(output_dir, os.path.basename(pdf))
            if not os.path.exists(page_dest):
                shutil.copy2(pdf, page_dest)
            saved_pdfs.append(page_dest)

        if len(pdf_files) == 1:
            final_path = saved_pdfs[0]
            shutil.rmtree(temp_extract, ignore_errors=True)
            logger.info(f"ACAD 转换成功（单页）: {final_path}")
            return final_path

        # 多个 PDF，合并为一个给 OCR 用
        final_path = os.path.join(output_dir, f"{base}.pdf")
        await _merge_pdfs(saved_pdfs, final_path)
        shutil.rmtree(temp_extract, ignore_errors=True)
        logger.info(f"ACAD 转换成功（{len(pdf_files)} 页合并）: {final_path}")
        return final_path

    except Exception as e:
        logger.warning(f"ACAD 结果处理失败: {e}")
        shutil.rmtree(temp_extract, ignore_errors=True)
        return None


async def _merge_pdfs(pdf_paths: list[str], output_path: str) -> None:
    """合并多个 PDF 文件为一个（使用系统 pdfunite）"""
    proc = await asyncio.create_subprocess_exec(
        "pdfunite", *pdf_paths, output_path,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise Exception(f"pdfunite 失败: {stderr.decode()[:200]}")


async def _convert_dwg_via_cad2x(input_path: str, output_dir: str) -> str | None:
    """用 cad2x 将 DWG/DXF 转为 PDF（单页）。返回 PDF 路径，失败返回 None。"""
    if not is_cad2x_available():
        logger.error("cad2x 不可用")
        return None

    base = os.path.splitext(os.path.basename(input_path))[0]
    pdf_path = os.path.join(output_dir, f"{base}.pdf")

    cmd = [
        _cad2x_path,
        "-o", pdf_path,
        input_path,
        "-ac",          # 自动方向 + 居中
        "-e", "ANSI_936",   # 简体中文编码
        "-f", "simsun",     # 宋体
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=get_settings().libreoffice_timeout)
        if proc.returncode == 0 and os.path.exists(pdf_path):
            logger.info(f"cad2x 转换成功: {pdf_path}")
            return pdf_path
        logger.warning(f"cad2x 转换失败: rc={proc.returncode}, stderr={stderr.decode()[:200]}")
    except asyncio.TimeoutError:
        logger.warning("cad2x 转换超时")
        try:
            proc.kill()
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"cad2x 异常: {e}")
    return None


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
