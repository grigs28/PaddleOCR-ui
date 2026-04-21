import asyncio
import json
import logging
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ProgressManager:
    """WebSocket 进度推送管理器"""

    def __init__(self):
        self.connections: dict[int, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        if user_id not in self.connections:
            self.connections[user_id] = []
        self.connections[user_id].append(websocket)
        logger.info(f"WebSocket 连接: user={user_id}")

    def disconnect(self, websocket: WebSocket, user_id: int):
        if user_id in self.connections:
            self.connections[user_id] = [
                ws for ws in self.connections[user_id] if ws != websocket
            ]
            if not self.connections[user_id]:
                del self.connections[user_id]

    async def send_progress(self, user_id: int, task_id: int, data: dict):
        """向用户推送任务进度"""
        if user_id not in self.connections:
            return
        message = json.dumps({"task_id": task_id, **data}, ensure_ascii=False)
        dead = []
        for ws in self.connections[user_id]:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.connections[user_id].remove(ws)


progress_manager = ProgressManager()
