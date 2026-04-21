import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy import select

from backend.auth.session import SessionManager
from backend.config import get_settings
from backend.database import async_session
from backend.models.user import User
from backend.auth.api_key import ApiKeyManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["认证"])

session_mgr = SessionManager()
settings = get_settings()

# Cookie 名
_COOKIE_NAME = settings.session_cookie_name


def get_current_user(request: Request) -> dict:
    session_id = request.cookies.get(_COOKIE_NAME)
    if not session_id:
        raise HTTPException(status_code=401, detail="未登录")
    user = session_mgr.get_session(session_id)
    if not user:
        raise HTTPException(status_code=401, detail="Session 已过期")
    return user


async def get_api_key_user(request: Request) -> dict:
    api_key = request.headers.get("X-API-Key")
    if not api_key:
        raise HTTPException(status_code=401, detail="缺少 X-API-Key 请求头")
    result = await ApiKeyManager.verify_key(api_key)
    if not result:
        raise HTTPException(status_code=401, detail="API Key 无效或已吊销")
    async with async_session() as session:
        user_result = await session.execute(select(User).where(User.id == result["user_id"]))
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
async def login():
    """跳转到 OOS 统一登录"""
    yz_url = settings.yz_login_url
    callback = settings.callback_url
    login_url = f"{yz_url}/login?from={callback}"
    logger.info(f"SSO redirect: {login_url}")
    return RedirectResponse(url=login_url, status_code=302)


@router.get("/callback")
async def callback(request: Request):
    """OOS 回调：用 ticket 换取用户信息"""
    ticket = request.query_params.get("ticket")
    if not ticket:
        logger.warning("callback 缺少 ticket 参数")
        return RedirectResponse(url="/", status_code=302)

    yz_url = settings.yz_login_url
    verify_url = f"{yz_url}/api/ticket/verify"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(verify_url, params={"ticket": ticket})
            logger.info(f"OOS verify: HTTP {resp.status_code}, body={resp.text[:200]}")

            if resp.status_code != 200:
                logger.warning(f"ticket 验证失败: HTTP {resp.status_code}")
                return RedirectResponse(url="/", status_code=302)

            data = resp.json()
            if not data.get("ok"):
                logger.warning(f"ticket 验证失败: {data.get('msg', 'unknown')}")
                return RedirectResponse(url="/", status_code=302)

        # 同步用户到本地数据库
        async with async_session() as db:
            result = await db.execute(
                select(User).where(User.username == data["username"])
            )
            user = result.scalar_one_or_none()
            # 白名单管理员 — 只用白名单控制管理员身份
            admin_list = [u.strip() for u in settings.admin_usernames.split(",")]
            is_admin_val = 1 if data["username"] in admin_list else 0
            if not user:
                user = User(
                    username=data["username"],
                    display_name=data.get("display_name", data["username"]),
                    is_admin=is_admin_val,
                )
                db.add(user)
                await db.commit()
                await db.refresh(user)
            else:
                changed = False
                if user.display_name != data.get("display_name", user.display_name):
                    user.display_name = data["display_name"]
                    changed = True
                if user.is_admin != is_admin_val:
                    user.is_admin = is_admin_val
                    changed = True
                if changed:
                    user.updated_at = datetime.now()
                    await db.commit()

            # 创建 Session
            session_id = session_mgr.create_session(
                user_id=user.id,
                username=user.username,
                display_name=user.display_name,
                is_admin=user.is_admin,
            )

        logger.info(f"SSO 登录成功: {user.display_name} (admin={user.is_admin})")

        # 通过 HTML 页面设置 cookie 并跳转（避免浏览器丢弃重定向中的 Set-Cookie）
        from starlette.responses import HTMLResponse
        html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>登录成功</title></head>
<body>
<p>登录成功，正在跳转...</p>
<script>
document.cookie = "{_COOKIE_NAME}={session_id}; path=/; max-age={settings.session_expire_hours * 3600}; SameSite=Lax";
window.location.href = "/";
</script>
</body></html>"""
        return HTMLResponse(content=html)

    except Exception as e:
        logger.error(f"SSO 回调异常: {e}")
        return RedirectResponse(url="/", status_code=302)


@router.post("/logout")
async def logout(request: Request):
    session_id = request.cookies.get(_COOKIE_NAME)
    if session_id:
        session_mgr.delete_session(session_id)
    response = JSONResponse(content={"message": "已登出"})
    response.delete_cookie(_COOKIE_NAME)
    return response


@router.get("/me")
async def me(request: Request):
    user = get_current_user(request)
    # 从数据库刷新 is_admin，确保与白名单一致
    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user["user_id"]))
        db_user = result.scalar_one_or_none()
        if db_user:
            user["is_admin"] = db_user.is_admin
            user["display_name"] = db_user.display_name
    return {
        "user_id": user["user_id"],
        "username": user["username"],
        "display_name": user["display_name"],
        "is_admin": user["is_admin"],
    }


@router.post("/api-keys")
async def create_api_key(request: Request, name: str = "默认"):
    user = get_current_user(request)
    raw_key = await ApiKeyManager.create_key(user_id=user["user_id"], name=name)
    return {"api_key": raw_key, "message": "请妥善保存，此 Key 仅显示一次"}


@router.get("/api-keys")
async def list_api_keys(request: Request):
    user = get_current_user(request)
    keys = await ApiKeyManager.list_keys(user["user_id"])
    return {"api_keys": keys}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key(key_id: int, request: Request):
    user = get_current_user(request)
    success = await ApiKeyManager.revoke_key(key_id, user["user_id"])
    if not success:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    return {"message": "API Key 已吊销"}


@router.get("/api-keys/{key_id}/reveal")
async def reveal_api_key(key_id: int, request: Request):
    """查看完整 API Key（内网环境）"""
    user = get_current_user(request)
    async with async_session() as session:
        from backend.models.api_key import ApiKey
        result = await session.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user["user_id"])
        )
        key_obj = result.scalar_one_or_none()
        if not key_obj:
            raise HTTPException(status_code=404, detail="API Key 不存在")
        return {"api_key": key_obj.api_key}
