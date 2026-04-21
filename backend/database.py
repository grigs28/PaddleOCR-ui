import re
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.dialects.postgresql.base import PGDialect
from backend.config import get_settings


class Base(DeclarativeBase):
    pass


# openGauss 兼容: 修补版本解析
_orig_get_server_version_info = PGDialect._get_server_version_info


def _patched_get_server_version_info(self, connection):
    try:
        return _orig_get_server_version_info(self, connection)
    except AssertionError:
        # openGauss 返回格式: "(openGauss-lite 7.0.0-RC1 build xxx)"
        return (7, 0, 0)


PGDialect._get_server_version_info = _patched_get_server_version_info


def create_engine():
    settings = get_settings()
    return create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
    )


engine = create_engine()
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
