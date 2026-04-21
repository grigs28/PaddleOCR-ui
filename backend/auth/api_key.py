import secrets
from datetime import datetime
from sqlalchemy import select, update
from backend.database import async_session
from backend.models.api_key import ApiKey

API_KEY_PREFIX = "ak_"

class ApiKeyManager:
    @staticmethod
    def generate_api_key() -> str:
        return API_KEY_PREFIX + secrets.token_hex(31)

    @staticmethod
    async def create_key(user_id: int, name: str) -> str:
        raw_key = ApiKeyManager.generate_api_key()
        async with async_session() as session:
            api_key = ApiKey(user_id=user_id, api_key=raw_key, name=name, is_active=1)
            session.add(api_key)
            await session.commit()
        return raw_key

    @staticmethod
    async def verify_key(api_key: str) -> dict | None:
        if not api_key.startswith(API_KEY_PREFIX):
            return None
        async with async_session() as session:
            result = await session.execute(
                select(ApiKey).where(ApiKey.api_key == api_key, ApiKey.is_active == 1)
            )
            key_obj = result.scalar_one_or_none()
            if not key_obj:
                return None
            await session.execute(
                update(ApiKey).where(ApiKey.id == key_obj.id).values(last_used_at=datetime.now())
            )
            await session.commit()
            return {"user_id": key_obj.user_id, "api_key_id": key_obj.id}

    @staticmethod
    async def revoke_key(api_key_id: int, user_id: int) -> bool:
        async with async_session() as session:
            result = await session.execute(
                update(ApiKey).where(ApiKey.id == api_key_id, ApiKey.user_id == user_id).values(is_active=0)
            )
            await session.commit()
            return result.rowcount > 0

    @staticmethod
    async def list_keys(user_id: int) -> list[dict]:
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
