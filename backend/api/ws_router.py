from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.auth.session import SessionManager
from backend.config import get_settings
from backend.ws.progress import progress_manager

router = APIRouter(tags=["WebSocket"])

session_mgr = SessionManager()
settings = get_settings()


@router.websocket("/ws/progress")
async def ws_progress(websocket: WebSocket):
    """WebSocket 进度推送端点"""
    # 从 query param 获取 session_id
    session_id = websocket.query_params.get("session_id")
    if not session_id:
        await websocket.close(code=4001, reason="缺少 session_id")
        return

    user = session_mgr.get_session(session_id)
    if not user:
        await websocket.close(code=4001, reason="无效 session")
        return

    user_id = user["user_id"]
    await progress_manager.connect(websocket, user_id)

    try:
        while True:
            # 保持连接，等待客户端消息或断开
            await websocket.receive_text()
    except WebSocketDisconnect:
        progress_manager.disconnect(websocket, user_id)
