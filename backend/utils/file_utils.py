import os
import uuid
from pathlib import Path
from backend.config import get_settings

ALLOWED_EXTENSIONS = {
    # PDF
    "pdf",
    # 图片（PaddleOCR 直接支持）
    "jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp",
    # Word（LibreOffice 转 PDF）
    "doc", "docx", "odt", "rtf",
    # Excel（LibreOffice 转 PDF）
    "xls", "xlsx", "ods", "csv",
    # 演示文稿（LibreOffice 转 PDF）
    "ppt", "pptx", "odp",
    # 文本/网页（LibreOffice 转 PDF）
    "txt", "html", "htm",
    # CAD（cad2x 转 PDF）
    "dwg", "dxf",
}

MIME_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "png": "application/png", "bmp": "image/bmp",
    "tiff": "image/tiff", "tif": "image/tiff", "webp": "image/webp",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "application/rtf",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "csv": "text/csv",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odp": "application/vnd.oasis.opendocument.presentation",
    "txt": "text/plain",
    "html": "text/html", "htm": "text/html",
    "dwg": "application/dwg", "dxf": "application/dxf",
}

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp"}
PDF_EXTENSIONS = {"pdf"}
CAD_EXTENSIONS = {"dwg", "dxf"}
# 非 PDF/图片/CAD 的格式，走 LibreOffice 转 PDF
DOC_EXTENSIONS = ALLOWED_EXTENSIONS - IMAGE_EXTENSIONS - PDF_EXTENSIONS - CAD_EXTENSIONS

def generate_task_id() -> str:
    return uuid.uuid4().hex[:16]

def get_file_extension(filename: str) -> str:
    return Path(filename).suffix.lstrip(".").lower()

def is_allowed_file(filename: str) -> bool:
    return get_file_extension(filename) in ALLOWED_EXTENSIONS

def is_image_file(filename: str) -> bool:
    return get_file_extension(filename) in IMAGE_EXTENSIONS

def is_pdf_file(filename: str) -> bool:
    return get_file_extension(filename) in PDF_EXTENSIONS

def is_doc_file(filename: str) -> bool:
    return get_file_extension(filename) in DOC_EXTENSIONS

def is_cad_file(filename: str) -> bool:
    return get_file_extension(filename) in CAD_EXTENSIONS

def get_mime_type(filename: str) -> str:
    ext = get_file_extension(filename)
    return MIME_TYPES.get(ext, "application/octet-stream")

def get_upload_path(task_id: str) -> str:
    settings = get_settings()
    path = os.path.join(settings.upload_dir, task_id)
    os.makedirs(path, exist_ok=True)
    return path

def get_result_path(task_id: str) -> str:
    settings = get_settings()
    path = os.path.join(settings.result_dir, task_id)
    os.makedirs(path, exist_ok=True)
    return path

def format_file_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

def sanitize_filename(filename: str) -> str:
    filename = os.path.basename(filename)
    for char in ["..", "/", "\\", "\0"]:
        filename = filename.replace(char, "")
    return filename or "unnamed"
