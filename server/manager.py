import logging
from collections import defaultdict

from fastapi import WebSocket


logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections[user_id].add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        connections = self.active_connections.get(user_id)
        if not connections:
            return
        connections.discard(websocket)
        if not connections:
            self.active_connections.pop(user_id, None)

    async def send_to_users(self, message: dict, *user_ids: int) -> None:
        for user_id in set(user_ids):
            for websocket in list(self.active_connections.get(user_id, ())):
                try:
                    await websocket.send_json(message)
                except Exception:
                    logger.exception("Failed to deliver a message to user %s", user_id)
                    self.disconnect(user_id, websocket)


manager = ConnectionManager()
