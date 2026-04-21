# 后端基础实施计划

**日期**: 2026-04-18
**范围**: 后端基础 + 数据库 + 认证模块
**设计文档**: [2026-04-18-paddleocr-ui-design.md](../specs/2026-04-18-paddleocr-ui-design.md)

---

## Task 1: 项目初始化

**Files:**
- Create: `backend/__init__.py`
- Create: `requirements.txt`
- Create: `backend/config.py`
- Create: `backend/main.py`

- [ ] **Step 1: 创建 backend 目录**

```bash
mkdir -p /opt/webapp/PaddleOCR-ui/backend
```

- [ ] **Step 2: 创建 backend/__init__.py**

```python
# backend/__init__.py
```

- [ ] **Step 3: 创建 requirements.txt**

```
fastapi==0.115.12
uvicorn[standard]==0.34.2
sqlalchemy[asyncio]==2.0.40
asyncpg==0.30.0
python-multipart==0.0.20
aiohttp==3.12.6
pyjwt==2.10.1
pydantic-settings==2.9.1
python-docx==1.1.2
openpyxl==3.1.5
PyMuPDF==1.25.5
pandoc==2.4
```

- [ ] **Step 4: 创建 backend/config.py**

```python
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # 数据库配置
    db_host: str = "192.168.0.98"
    db_port: int = 5432
    db_user: str = "grigs"
    db_password: str = "Slnwg123$"
    db_name: str = "paddleocr_ui"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # OCR 服务配置
    ocr_service_url: str = "http://192.168.0.70:5564/v1"
    ocr_model_name: str = "PaddleOCR-VL-1.5-0.9B"

    # yz-login 配置
    yz_login_url: str = "http://192.168.0.19:5555"

    # 应用配置
    app_host: str = "0.0.0.0"
    app_port: int = 8080
    secret_key: str = "paddleocr-ui-secret-key-change-in-production"
    session_cookie_name: str = "paddleocr_session"
    session_expire_hours: int = 24

    # 文件配置
    upload_dir: str = "data/uploads"
    result_dir: str = "data/results"
    temp_dir: str = "data/temp"
    max_file_size_mb: int = 100
    allowed_file_types: str = "pdf,jpg,jpeg,png,bmp,tiff,tif,docx,xlsx"

    # 任务引擎配置
    max_concurrency: int = 3

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 5: 创建 backend/main.py**

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：创建必要目录
    settings = get_settings()
    for dir_path in [settings.upload_dir, settings.result_dir, settings.temp_dir]:
        os.makedirs(dir_path, exist_ok=True)
    yield
    # 关闭时：清理资源（后续添加）


app = FastAPI(
    title="PaddleOCR Web UI",
    description="基于 PaddleOCR-VL 的 Web OCR 服务",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
```

- [ ] **Step 6: 验证**

```bash
cd /opt/webapp/PaddleOCR-ui
pip install -r requirements.txt
python -c "from backend.config import get_settings; s = get_settings(); print(s.database_url)"
python -c "from backend.main import app; print(app.title)"
```

- [ ] **Step 7: Commit**

```bash
git add backend/__init__.py requirements.txt backend/config.py backend/main.py
git commit -m "feat: 项目初始化 - FastAPI 入口、配置管理、依赖声明"
```

---

## Task 2: 数据库连接

**Files:**
- Create: `backend/database.py`

- [ ] **Step 1: 创建 backend/database.py**

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from backend.config import get_settings


class Base(DeclarativeBase):
    pass


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
```

- [ ] **Step 2: 验证**

```bash
cd /opt/webapp/PaddleOCR-ui
python -c "from backend.database import engine, async_session, Base; print('DB engine created:', engine.url)"
```

- [ ] **Step 3: Commit**

```bash
git add backend/database.py
git commit -m "feat: 数据库连接 - openGauss 异步连接池配置"
```

---

## Task 3: ORM 模型

**Files:**
- Create: `backend/models/__init__.py`
- Create: `backend/models/user.py`
- Create: `backend/models/task.py`
- Create: `backend/models/api_key.py`
- Create: `backend/models/system_config.py`

- [ ] **Step 1: 创建 backend/models/__init__.py**

```python
from backend.models.user import User
from backend.models.task import Task
from backend.models.api_key import ApiKey
from backend.models.system_config import SystemConfig

__all__ = ["User", "Task", "ApiKey", "SystemConfig"]
```

- [ ] **Step 2: 创建 backend/models/user.py**

```python
from datetime import datetime
from sqlalchemy import BigInteger, String, SmallInteger, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100))
    is_admin: Mapped[int] = mapped_column(SmallInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 3: 创建 backend/models/task.py**

```python
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
```

- [ ] **Step 4: 创建 backend/models/api_key.py**

```python
from datetime import datetime
from sqlalchemy import BigInteger, String, SmallInteger, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    api_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[int] = mapped_column(SmallInteger, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
```

- [ ] **Step 5: 创建 backend/models/system_config.py**

```python
from datetime import datetime
from sqlalchemy import String, Text, DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.database import Base


class SystemConfig(Base):
    __tablename__ = "system_config"

    config_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    config_value: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
```

- [ ] **Step 6: 验证**

```bash
cd /opt/webapp/PaddleOCR-ui
python -c "from backend.models import User, Task, ApiKey, SystemConfig; print('Models loaded:', User.__tablename__, Task.__tablename__, ApiKey.__tablename__, SystemConfig.__tablename__)"
```

- [ ] **Step 7: Commit**

```bash
git add backend/models/__init__.py backend/models/user.py backend/models/task.py backend/models/api_key.py backend/models/system_config.py
git commit -m "feat: ORM 模型 - users/tasks/api_keys/system_config 四张表"
```

---

## Task 4: 数据库初始化脚本

**Files:**
- Create: `backend/init_db.py`

- [ ] **Step 1: 创建 backend/init_db.py**

```python
import asyncio
from sqlalchemy import text

from backend.database import engine, async_session, Base
from backend.models import User, Task, ApiKey, SystemConfig

# 默认系统配置
DEFAULT_CONFIGS = [
    {
        "config_key": "max_concurrency",
        "config_value": "3",
        "description": "最大并发任务数",
    },
    {
        "config_key": "max_file_size_mb",
        "config_value": "100",
        "description": "最大文件大小(MB)",
    },
    {
        "config_key": "allowed_file_types",
        "config_value": "pdf,jpg,jpeg,png,bmp,tiff,tif,docx,xlsx",
        "description": "允许的文件类型",
    },
    {
        "config_key": "queue_paused",
        "config_value": "0",
        "description": "队列是否暂停(0/1)",
    },
]


async def init_db():
    async with engine.begin() as conn:
        # 创建所有表
        await conn.run_sync(Base.metadata.create_all)
        print("所有表创建成功")

    # 插入默认系统配置
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
```

- [ ] **Step 2: 验证**

```bash
cd /opt/webapp/PaddleOCR-ui
python -c "from backend.init_db import DEFAULT_CONFIGS; print('Config count:', len(DEFAULT_CONFIGS))"
# 实际运行（需要数据库可达）:
# python -m backend.init_db
```

- [ ] **Step 3: Commit**

```bash
git add backend/init_db.py
git commit -m "feat: 数据库初始化脚本 - 建表 + 默认系统配置"
```

---

## Task 5: 认证模块 - yz-login 集成

**Files:**
- Create: `backend/auth/__init__.py`
- Create: `backend/auth/yz_login.py`
- Create: `backend/auth/session.py`

- [ ] **Step 1: 创建 backend/auth/ 目录**

```bash
mkdir -p /opt/webapp/PaddleOCR-ui/backend/auth
```

- [ ] **Step 2: 创建 backend/auth/__init__.py**

```python
from backend.auth.yz_login import YZLoginClient
from backend.auth.session import SessionManager
from backend.auth.api_key import ApiKeyManager

__all__ = ["YZLoginClient", "SessionManager", "ApiKeyManager"]
```

- [ ] **Step 3: 创建 backend/auth/yz_login.py**

```python
import aiohttp
from backend.config import get_settings


class YZLoginClient:
    """yz-login Ticket 认证客户端"""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.yz_login_url

    def get_login_url(self, callback_url: str) -> str:
        """生成 yz-login 登录跳转 URL"""
        return f"{self.base_url}/login?from={callback_url}"

    async def verify_ticket(self, ticket: str) -> dict | None:
        """
        验证 Ticket 并返回用户信息

        返回格式:
        {
            "username": "xxx",
            "display_name": "显示名"
        }
        验证失败返回 None
        """
        async with aiohttp.ClientSession() as client:
            url = f"{self.base_url}/api/ticket/verify"
            params = {"ticket": ticket}
            try:
                async with client.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        return None
                    data = await resp.json()
                    if not data or not data.get("username"):
                        return None
                    return {
                        "username": data["username"],
                        "display_name": data.get("display_name", data["username"]),
                    }
            except (aiohttp.ClientError, asyncio.TimeoutError):
                return None


import asyncio
```

- [ ] **Step 4: 创建 backend/auth/session.py**

```python
import secrets
import time
from typing import Optional

from backend.database import async_session


# 内存 Session 存储: session_id -> {user_id, username, display_name, is_admin, expires_at}
_sessions: dict[str, dict] = {}


class SessionManager:
    """本地 Session 管理器（内存存储 + Cookie）"""

    def __init__(self, expire_hours: int = 24):
        self.expire_seconds = expire_hours * 3600

    def create_session(
        self,
        user_id: int,
        username: str,
        display_name: str,
        is_admin: int = 0,
    ) -> str:
        """创建 Session，返回 session_id"""
        session_id = secrets.token_hex(32)
        _sessions[session_id] = {
            "user_id": user_id,
            "username": username,
            "display_name": display_name,
            "is_admin": is_admin,
            "expires_at": time.time() + self.expire_seconds,
        }
        return session_id

    def get_session(self, session_id: str) -> Optional[dict]:
        """获取 Session 信息，过期或不存在返回 None"""
        session = _sessions.get(session_id)
        if not session:
            return None
        if time.time() > session["expires_at"]:
            _sessions.pop(session_id, None)
            return None
        return session

    def delete_session(self, session_id: str) -> None:
        """删除 Session"""
        _sessions.pop(session_id, None)

    def refresh_session(self, session_id: str) -> None:
        """续期 Session"""
        session = _sessions.get(session_id)
        if session:
            session["expires_at"] = time.time() + self.expire_seconds
```

- [ ] **Step 5: 验证**

```bash
cd /opt/webapp/PaddleOCR-ui
python -c "from backend.auth.yz_login import YZLoginClient; c = YZLoginClient(); print('Login URL:', c.get_login_url('http://localhost:8080/auth/callback'))"
python -c "from backend.auth.session import SessionManager; m = SessionManager(); sid = m.create_session(1, 'test', 'Test User'); print('Session:', m.get_session(sid))"
```

- [ ] **Step 6: Commit**

```bash
git add backend/auth/__init__.py backend/auth/yz_login.py backend/auth/session.py
git commit -m "feat: yz-login 认证集成 - Ticket 验证 + 本地 Session 管理"
```

---

## Task 6: 认证模块 - API Key

**Files:**
- Create: `backend/auth/api_key.py`

- [ ] **Step 1: 创建 backend/auth/api_key.py**

```python
import secrets
from datetime import datetime

from sqlalchemy import select, update

from backend.database import async_session
from backend.models.api_key import ApiKey


API_KEY_PREFIX = "ak_"


class ApiKeyManager:
    """API Key 生成与验证"""

    @staticmethod
    def generate_api_key() -> str:
        """生成 API Key: ak_ + 62 字符随机十六进制"""
        return API_KEY_PREFIX + secrets.token_hex(31)

    @staticmethod
    async def create_key(user_id: int, name: str) -> str:
        """为用户创建 API Key，返回明文 key（仅此一次可见）"""
        raw_key = ApiKeyManager.generate_api_key()
        async with async_session() as session:
            api_key = ApiKey(
                user_id=user_id,
                api_key=raw_key,
                name=name,
                is_active=1,
            )
            session.add(api_key)
            await session.commit()
        return raw_key

    @staticmethod
    async def verify_key(api_key: str) -> dict | None:
        """
        验证 API Key，返回用户信息或 None

        返回格式: {"user_id": int, "api_key_id": int}
        """
        if not api_key.startswith(API_KEY_PREFIX):
            return None
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(
                    ApiKey.api_key == api_key,
                    ApiKey.is_active == 1,
                )
            )
            key_obj = result.scalar_one_or_none()
            if not key_obj:
                return None
            # 更新最后使用时间
            await session.execute(
                update(ApiKey)
                .where(ApiKey.id == key_obj.id)
                .values(last_used_at=datetime.now())
            )
            await session.commit()
            return {
                "user_id": key_obj.user_id,
                "api_key_id": key_obj.id,
            }

    @staticmethod
    async def revoke_key(api_key_id: int, user_id: int) -> bool:
        """吊销 API Key"""
        async with async_session() as session:
            result = await session.execute(
                update(ApiKey)
                .where(ApiKey.id == api_key_id, ApiKey.user_id == user_id)
                .values(is_active=0)
            )
            await session.commit()
            return result.rowcount > 0

    @staticmethod
    async def list_keys(user_id: int) -> list[dict]:
        """列出用户的所有 API Key"""
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.user_id == user_id).order_by(ApiKey.created_at.desc())
            )
            keys = result.scalars().all()
            return [
                {
                    "id": k.id,
                    "name": k.name,
                    "api_key_prefix": k.api_key[:6] + "..." + k.api_key[-4:],
                    "is_active": k.is_active,
                    "created_at": k.created_at.isoformat() if k.created_at else None,
                    "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
                }
                for k in keys
            ]
```

- [ ] **Step 2: 验证**

```bash
cd /opt/webapp/PaddleOCR-ui
python -c "from backend.auth.api_key import ApiKeyManager; key = ApiKeyManager.generate_api_key(); print('Generated key:', key, 'len:', len(key))"
```

- [ ] **Step 3: Commit**

```bash
git add backend/auth/api_key.py
git commit -m "feat: API Key 认证 - 生成、验证、吊销、列表"
```

---

## Task 7: 认证路由

**Files:**
- Create: `backend/api/__init__.py`
- Create: `backend/api/auth_router.py`

- [ ] **Step 1: 创建 backend/api/ 目录**

```bash
mkdir -p /opt/webapp/PaddleOCR-ui/backend/api
```

- [ ] **Step 2: 创建 backend/api/__init__.py**

```python
# backend/api/__init__.py
```

- [ ] **Step 3: 创建 backend/api/auth_router.py**

```python
from datetime import datetime
from fastapi import APIRouter, Request, Response, Depends, HTTPException
from sqlalchemy import select

from backend.auth.yz_login import YZLoginClient
from backend.auth.session import SessionManager
from backend.config import get_settings
from backend.database import get_db, async_session
from backend.models.user import User
from backend.models.api_key import ApiKey
from backend.auth.api_key import ApiKeyManager

router = APIRouter(prefix="/auth", tags=["认证"])

yz_client = YZLoginClient()
session_mgr = SessionManager()
settings = get_settings()


def get_current_user(request: Request) -> dict:
    """从 Cookie 获取当前用户，未登录抛 401"""
    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")
    user = session_mgr.get_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Session 已过期")
    return user


async def get_api_key_user(request: Request) -> dict:
    """从 X-API-Key 请求头获取用户，验证失败抛 401"""
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="缺少 X-API-Key 请求头")
    result = await ApiKeyManager.verify_key(api_key)
    if not result:
        raise HTTPException(status_code=401, detail="API Key 无效或已吊销")
    # 查询用户信息
    async with async_session() as session:
        user_result = await session.execute(
            select(User).where(User.id == result["user_id"])
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")
        return {
            "user_id": user.id,
            "username": user.username,
            "display_name": user.display_name,
            "is_admin": user.is_admin,
        }


@router.get("/login")
async def login(request: Request):
    """跳转到 yz-login 登录页"""
    callback_url = str(request.base_url) + "auth/callback"
    login_url = yz_client.get_login_url(callback_url)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=login_url)


@router.get("/callback")
async def callback(ticket: str, response: Response):
    """yz-login 登录回调，验证 Ticket 并创建本地 Session"""
    user_info = await yz_client.verify_ticket(ticket)
    if not user_info:
        raise HTTPException(status_code=401, detail="Ticket 验证失败")

    # 同步用户到本地数据库
    async with async_session() as db:
        result = await db.execute(
            select(User).where(User.username == user_info["username"])
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                username=user_info["username"],
                display_name=user_info["display_name"],
                is_admin=0,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
        else:
            # 更新显示名
            if user.display_name != user_info["display_name"]:
                user.display_name = user_info["display_name"]
                user.updated_at = datetime.now()
                await db.commit()

        # 创建 Session
        session_id = session_mgr.create_session(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
        )

    # 设置 Cookie 并重定向到首页
    from fastapi.responses import RedirectResponse
    response = RedirectResponse(url="/")
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_id,
        httponly=True,
        max_age=settings.session_expire_hours * 3600,
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout(request: Request):
    """登出，删除 Session 和 Cookie"""
    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        session_mgr.delete_session(session_id)
    from fastapi.responses import JSONResponse
    response = JSONResponse(content={"message": "已登出"})
    response.delete_cookie(settings.session_cookie_name)
    return response


@router.get("/me")
async def me(request: Request):
    """获取当前登录用户信息"""
    user = get_current_user(request)
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "is_admin": user["is_admin"],
    }


@router.post("/api-keys")
async def create_api_key(request: Request, name: str = "默认"):
    """创建 API Key"""
    user = get_current_user(request)
    raw_key = await ApiKeyManager.create_key(user_id=user["user_id"], name=name)
    return {"api_key": raw_key, "message": "请妥善保存，此 Key 仅显示一次"}


@router.get("/api-keys")
async def list_api_keys(request: Request):
    """列出当前用户的 API Key"""
    user = get_current_user(request)
    keys = await ApiKeyManager.list_keys(user["user_id"])
    return {"api_keys": keys}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: int, request: Request):
    """吊销 API Key"""
    user = get_current_user(request)
    success = await ApiKeyManager.revoke_key(key_id, user["user_id"])
    if not success:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    return {"message": "API Key 已吊销"}
```

- [ ] **Step 4: 更新 backend/main.py，注册认证路由**

在 `backend/main.py` 中添加路由注册：

```python
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import get_settings
from backend.api.auth_router import router as auth_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    for dir_path in [settings.upload_dir, settings.result_dir, settings.temp_dir]:
        os.makedirs(dir_path, exist_ok=True)
    yield


app = FastAPI(
    title="PaddleOCR Web UI",
    description="基于 PaddleOCR-VL 的 Web OCR 服务",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
```

- [ ] **Step 5: 验证**

```bash
cd /opt/webapp/PaddleOCR-ui
python -c "from backend.main import app; routes = [r.path for r in app.routes]; print('Routes:', routes)"
```

- [ ] **Step 6: Commit**

```bash
git add backend/api/__init__.py backend/api/auth_router.py backend/main.py
git commit -m "feat: 认证路由 - 登录/登出/callback/API Key 管理"
```

---

## Task 8: 通用工具

**Files:**
- Create: `backend/utils/__init__.py`
- Create: `backend/utils/file_utils.py`

- [ ] **Step 1: 创建 backend/utils/ 目录**

```bash
mkdir -p /opt/webapp/PaddleOCR-ui/backend/utils
```

- [ ] **Step 2: 创建 backend/utils/__init__.py**

```python
# backend/utils/__init__.py
```

- [ ] **Step 3: 创建 backend/utils/file_utils.py**

```python
import os
import uuid
from pathlib import Path

from backend.config import get_settings


ALLOWED_EXTENSIONS = {
    "pdf", "jpg", "jpeg", "png", "bmp", "tiff", "tif", "docx", "xlsx",
}

MIME_TYPES = {
    "pdf": "application/pdf",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "tif": "image/tiff",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def generate_task_id() -> str:
    """生成唯一任务 ID"""
    return uuid.uuid4().hex[:16]


def get_file_extension(filename: str) -> str:
    """获取文件扩展名（小写，无点）"""
    return Path(filename).suffix.lstrip(".").lower()


def is_allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    ext = get_file_extension(filename)
    return ext in ALLOWED_EXTENSIONS


def get_mime_type(filename: str) -> str:
    """获取文件的 MIME 类型"""
    ext = get_file_extension(filename)
    return MIME_TYPES.get(ext, "application/octet-stream")


def get_upload_path(task_id: str) -> str:
    """获取上传文件目录"""
    settings = get_settings()
    path = os.path.join(settings.upload_dir, task_id)
    os.makedirs(path, exist_ok=True)
    return path


def get_result_path(task_id: str) -> str:
    """获取结果文件目录"""
    settings = get_settings()
    path = os.path.join(settings.result_dir, task_id)
    os.makedirs(path, exist_ok=True)
    return path


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def sanitize_filename(filename: str) -> str:
    """清理文件名，移除危险字符"""
    filename = os.path.basename(filename)
    dangerous_chars = ["..", "/", "\\", "\0"]
    for char in dangerous_chars:
        filename = filename.replace(char, "")
    return filename or "unnamed"
```

- [ ] **Step 4: 验证**

```bash
cd /opt/webapp/PaddleOCR-ui
python -c "
from backend.utils.file_utils import (
    generate_task_id, is_allowed_file, get_file_extension,
    get_mime_type, format_file_size, sanitize_filename
)
print('Task ID:', generate_task_id())
print('Allowed test.pdf:', is_allowed_file('test.pdf'))
print('Allowed test.exe:', is_allowed_file('test.exe'))
print('Ext:', get_file_extension('Photo.JPG'))
print('MIME:', get_mime_type('doc.pdf'))
print('Size:', format_file_size(1536000))
print('Sanitize:', sanitize_filename('../../../etc/passwd'))
"
```

- [ ] **Step 5: Commit**

```bash
git add backend/utils/__init__.py backend/utils/file_utils.py
git commit -m "feat: 文件工具函数 - 扩展名检查、路径生成、文件名清理"
```

---

## 最终目录结构

完成所有 Task 后，项目结构如下：

```
backend/
├── __init__.py
├── config.py                 # pydantic-settings 配置管理
├── database.py               # openGauss 异步连接池
├── main.py                   # FastAPI 入口 + CORS + 路由注册
├── init_db.py                # 数据库初始化脚本
├── auth/
│   ├── __init__.py
│   ├── yz_login.py           # yz-login Ticket 验证
│   ├── session.py            # 内存 Session 管理
│   └── api_key.py            # API Key 生成/验证/吊销
├── models/
│   ├── __init__.py
│   ├── user.py               # users 表 ORM
│   ├── task.py               # tasks 表 ORM
│   ├── api_key.py            # api_keys 表 ORM
│   └── system_config.py      # system_config 表 ORM
├── api/
│   ├── __init__.py
│   └── auth_router.py        # 认证相关路由
└── utils/
    ├── __init__.py
    └── file_utils.py          # 文件处理工具
requirements.txt               # Python 依赖
```
