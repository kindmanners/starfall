import logging
from collections import defaultdict

from fastapi import WebSocket


logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[int, dict[str, set[WebSocket]]] = defaultdict(
            lambda: defaultdict(set)
        )

    async def connect(self, user_id: int, jti: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections[user_id][jti].add(websocket)

    def disconnect(self, user_id: int, jti: str, websocket: WebSocket) -> None:
        sessions = self.active_connections.get(user_id)
        if not sessions:
            return
        connections = sessions.get(jti)
        if connections:
            connections.discard(websocket)
            if not connections:
                sessions.pop(jti, None)
        if not sessions:
            self.active_connections.pop(user_id, None)

    async def disconnect_session(self, jti: str, code: int = 4008) -> None:
        targets: list[tuple[int, WebSocket]] = []
        for user_id, sessions in list(self.active_connections.items()):
            for websocket in list(sessions.get(jti, ())):
                targets.append((user_id, websocket))
                self.disconnect(user_id, jti, websocket)
        for _, websocket in targets:
            try:
                await websocket.close(code=code)
            except Exception:
                logger.exception("Failed to close a revoked session socket")

    async def send_to_users(self, message: dict, *user_ids: int) -> None:
        for user_id in set(user_ids):
            sessions = self.active_connections.get(user_id, {})
            for jti, connections in list(sessions.items()):
                for websocket in list(connections):
                    try:
                        await websocket.send_json(message)
                    except Exception:
                        logger.exception("Failed to deliver a message to user %s", user_id)
                        self.disconnect(user_id, jti, websocket)


manager = ConnectionManager()
