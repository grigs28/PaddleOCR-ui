import secrets
import time
from typing import Optional

_sessions: dict[str, dict] = {}

class SessionManager:
    def __init__(self, expire_hours: int = 24):
        self.expire_seconds = expire_hours * 3600

    def create_session(self, user_id: int, username: str, display_name: str, is_admin: int = 0) -> str:
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
        session = _sessions.get(session_id)
        if not session:
            return None
        if time.time() > session["expires_at"]:
            _sessions.pop(session_id, None)
            return None
        return session

    def delete_session(self, session_id: str) -> None:
        _sessions.pop(session_id, None)

    def refresh_session(self, session_id: str) -> None:
        session = _sessions.get(session_id)
        if session:
            session["expires_at"] = time.time() + self.expire_seconds
