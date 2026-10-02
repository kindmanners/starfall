import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import Response, WebSocketDisconnect

from server import main
from server.manager import ConnectionManager
from server.security import create_token, decode_token


class FakeWebSocket:
    def __init__(self, origin: str | None = None):
        self.headers = {"origin": origin} if origin is not None else {}
        self.cookies = {"access_token": "test-token"}
        self.accepted = False
        self.closed_with = None

    async def accept(self):
        self.accepted = True

    async def close(self, code: int):
        self.closed_with = code

    async def receive_json(self):
        raise WebSocketDisconnect()

    async def send_json(self, _message):
        return None


class TokenTests(unittest.TestCase):
    def test_required_session_claims(self):
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        jti = str(uuid4())
        token = create_token({"user_id": 7, "jti": jti}, expires_at=expires)
        self.assertEqual(decode_token(token)["jti"], jti)
        missing_jti = create_token({"user_id": 7}, expires_at=expires)
        self.assertIsNone(decode_token(missing_jti))

    def test_expired_token_is_only_decodable_for_logout(self):
        expires = datetime.now(timezone.utc) - timedelta(seconds=1)
        token = create_token(
            {"user_id": 7, "jti": str(uuid4())}, expires_at=expires
        )
        self.assertIsNone(decode_token(token))
        self.assertIsNotNone(decode_token(token, verify_exp=False))


class ConnectionManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_session_only_closes_that_device(self):
        manager = ConnectionManager()
        first = FakeWebSocket()
        second = FakeWebSocket()
        await manager.connect(3, "first", first)
        await manager.connect(3, "second", second)

        await manager.disconnect_session("first")

        self.assertEqual(first.closed_with, 4008)
        self.assertIsNone(second.closed_with)
        self.assertIn("second", manager.active_connections[3])


class EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_websocket_rejects_untrusted_or_missing_origin(self):
        for origin in (None, "null", "https://evil.example", "https://wayfarer.angelfish-byzantine.ts.net:8443.evil.example"):
            websocket = FakeWebSocket(origin)
            await main.websocket_endpoint(websocket)
            self.assertFalse(websocket.accepted)
            self.assertEqual(websocket.closed_with, 1008)

    async def test_websocket_accepts_exact_origin_with_active_session(self):
        websocket = FakeWebSocket("https://wayfarer.angelfish-byzantine.ts.net:8443")
        expires = datetime.now(timezone.utc) + timedelta(minutes=5)
        user = {"id": 9, "username": "tester", "email": "t@example.com"}
        with (
            patch.object(main, "current_session", return_value=(user, "session", expires)),
            patch.object(main, "get_active_session", return_value={"jti": "session"}),
        ):
            await main.websocket_endpoint(websocket)
        self.assertTrue(websocket.accepted)
        self.assertIsNone(websocket.closed_with)

    async def test_logout_revokes_and_closes_exact_session(self):
        request = type("Request", (), {"cookies": {"access_token": "token"}})()
        response = Response()
        with (
            patch.object(main, "token_identity", return_value=(4, "session-jti")),
            patch.object(main, "revoke_session", return_value=True) as revoke,
            patch.object(main.manager, "disconnect_session", new=AsyncMock()) as close,
        ):
            await main.logout(request, response)
        revoke.assert_called_once_with("session-jti", 4)
        close.assert_awaited_once_with("session-jti")
        self.assertIn(b"access_token=", dict(response.raw_headers)[b"set-cookie"])


if __name__ == "__main__":
    unittest.main()
