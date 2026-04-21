import asyncio
import aiohttp
from backend.config import get_settings

class YZLoginClient:
    """OOS 统一登录 Ticket 认证客户端"""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.yz_login_url

    def get_login_url(self, callback_url: str) -> str:
        return f"{self.base_url}/login?from={callback_url}"

    async def verify_ticket(self, ticket: str) -> dict | None:
        async with aiohttp.ClientSession() as client:
            url = f"{self.base_url}/api/ticket/verify"
            params = {"ticket": ticket}
            try:
                async with client.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    # OOS 可能返回 200 或 403
                    data = await resp.json()
                    # OOS 返回格式: {"ok": true/false, "username": "xxx", ...}
                    if not data or not data.get("ok"):
                        return None
                    return {
                        "username": data.get("username", ""),
                        "display_name": data.get("display_name", data.get("username", "")),
                    }
            except (aiohttp.ClientError, asyncio.TimeoutError):
                return None
