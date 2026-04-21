import asyncio
from sqlalchemy import text
from backend.database import engine, async_session, Base
from backend.models import User, Task, ApiKey, SystemConfig

DEFAULT_CONFIGS = [
    {"config_key": "max_concurrency", "config_value": "4", "description": "最大并发任务数"},
    {"config_key": "max_file_size_mb", "config_value": "100", "description": "最大文件大小(MB)"},
    {"config_key": "allowed_file_types", "config_value": "pdf,jpg,jpeg,png,bmp,tiff,tif,webp,docx,xlsx", "description": "允许的文件类型"},
    {"config_key": "queue_paused", "config_value": "0", "description": "队列是否暂停(0/1)"},
]

async def _migrate(conn):
    """执行增量迁移：为已有表添加新字段"""
    migrations = [
        ("tasks", "processing_time", "ADD COLUMN processing_time INTEGER DEFAULT NULL"),
    ]
    for table, column, alter_sql in migrations:
        try:
            await conn.execute(text(f"SELECT {column} FROM {table} LIMIT 0"))
        except Exception:
            await conn.execute(text(f"ALTER TABLE {table} {alter_sql}"))
            print(f"迁移: {table}.{column} 已添加")


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)
        print("所有表创建成功")
    async with async_session() as session:
        for config in DEFAULT_CONFIGS:
            result = await session.execute(
                text("SELECT COUNT(*) FROM system_config WHERE config_key = :key"),
                {"key": config["config_key"]},
            )
            count = result.scalar()
            if count == 0:
                session.add(SystemConfig(**config))
                print(f"插入配置: {config['config_key']} = {config['config_value']}")
        await session.commit()
    print("默认配置插入完成")

if __name__ == "__main__":
    asyncio.run(init_db())
