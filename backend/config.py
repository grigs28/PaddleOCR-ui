from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    # 数据库配置
    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: str = "changeme"
    db_name: str = "paddleocr_ui"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # OCR 服务配置 (HPS 产线服务)
    ocr_service_url: str = "http://localhost:5564"

    # ACAD DWG 转 PDF 服务配置
    acad_service_url: str = "http://192.168.0.5:5557"
    acad_service_apikey: str = ""

    # PP-OCRv6 服务（零幻觉文字识别，0.71:5561）
    ppocrv6_service_url: str = "http://192.168.0.71:5561"
    # MinerU 服务（VLM 文档解析，0.71:5555）
    mineru_service_url: str = "http://192.168.0.71:5555"

    # OOS 统一登录配置
    yz_login_url: str = "http://localhost:5551"
    callback_url: str = "http://localhost:5553/auth/callback"

    # 应用配置
    app_host: str = "0.0.0.0"
    app_port: int = 5553
    secret_key: str = "change-this-in-production"
    session_cookie_name: str = "paddleocr_session"
    session_expire_hours: int = 24
    admin_usernames: str = "admin,grigs"  # 超级管理员用户名，逗号分隔

    # 文件配置
    upload_dir: str = "data/uploads"
    result_dir: str = "data/results"
    temp_dir: str = "data/temp"
    max_file_size_mb: int = 1024
    chunk_size: int = 4 * 1024 * 1024  # 分片大小 4MB
    allowed_file_types: str = "pdf,jpg,jpeg,png,bmp,tiff,tif,webp,docx,xlsx"

    # 任务引擎配置
    max_concurrency: int = 4
    # 图片和 PDF 分开队列
    image_semaphore_size: int = 4
    pdf_semaphore_size: int = 2
    acad_concurrency: int = 12
    acad_task_timeout: int = 3600     # ACAD 轮询超时兜底（秒），服务端自行管理转换超时

    # OCR 超时配置
    ocr_image_timeout: int = 300       # 单张图片 OCR 超时（秒）
    ocr_pdf_page_timeout: int = 30     # PDF 每页 OCR 超时（秒）
    libreoffice_timeout: int = 3600    # LibreOffice 转换超时（秒）
    ocr_health_timeout: int = 10       # OCR 健康检查超时（秒）

    # OCR VLM 参数（影响识别精度，尤其是密集表格）
    ocr_vlm_max_pixels: int = 2048 * 28 * 28          # 全局最大像素（默认 1536×1536 太小）
    ocr_vlm_table_max_pixels: int = 4096 * 28 * 28    # 表格区域最大像素（关键！）
    ocr_vlm_max_new_tokens: int = 8192                 # VLM 最大输出 token
    # 高精度模式（CAD 图纸 / 密集小字表格）：提高 VLM 输入分辨率，耗时 +50%
    ocr_vlm_max_pixels_high: int = 12700 * 28 * 28         # ~10MP（小字可读阈值）
    ocr_vlm_table_max_pixels_high: int = 25400 * 28 * 28   # ~20MP（表格区域）

    # 日志配置
    log_file: str = "data/logs/app.log"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

@lru_cache()
def get_settings() -> Settings:
    return Settings()
