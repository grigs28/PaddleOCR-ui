from datetime import datetime
from sqlalchemy import (
    BigInteger, String, Text, SmallInteger, Integer, DateTime, ForeignKey, func
)
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base

class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    task_type: Mapped[str | None] = mapped_column(String(20))
    input_filename: Mapped[str | None] = mapped_column(String(500))
    input_file_path: Mapped[str | None] = mapped_column(String(1000))
    input_file_size: Mapped[int | None] = mapped_column(BigInteger)
    output_formats: Mapped[str | None] = mapped_column(String(100))
    result_path: Mapped[str | None] = mapped_column(String(1000))
    error_message: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(SmallInteger, default=0)
    page_current: Mapped[int] = mapped_column(Integer, default=0)
    page_total: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    processing_time: Mapped[int | None] = mapped_column(Integer, default=None)  # 处理用时（秒）
    priority: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0=用户, 1=API, 2=管理员
    deleted: Mapped[int] = mapped_column(SmallInteger, default=0)  # 0=正常, 1=用户软删, 2=管理员硬删
