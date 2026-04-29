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

    # OCR 超时配置
    ocr_image_timeout: int = 300       # 单张图片 OCR 超时（秒）
    ocr_pdf_page_timeout: int = 30     # PDF 每页 OCR 超时（秒）
    libreoffice_timeout: int = 3600    # LibreOffice 转换超时（秒）
    ocr_health_timeout: int = 10       # OCR 健康检查超时（秒）

    # 日志配置
    log_file: str = "data/logs/app.log"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

@lru_cache()
def get_settings() -> Settings:
    return Settings()
