from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select

from backend.api.ocr_router import _get_user_id
from backend.database import async_session
from backend.models.user import User

router = APIRouter(prefix="/api/v1/admin", tags=["管理后台"])


async def _require_admin(request: Request) -> int:
    user_id = await _get_user_id(request)
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_admin:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user_id


@router.get("/users")
async def list_users(request: Request):
    await _require_admin(request)
    async with async_session() as session:
        result = await session.execute(select(User).order_by(User.id))
        users = result.scalars().all()
        return {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "is_admin": u.is_admin,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in users
            ]
        }


@router.put("/users/{user_id}")
async def update_user(user_id: int, request: Request):
    await _require_admin(request)
    body = await request.json()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if "is_admin" in body:
            user.is_admin = int(body["is_admin"])
        if "display_name" in body:
            user.display_name = body["display_name"]
        await session.commit()
        return {"message": "已更新"}
