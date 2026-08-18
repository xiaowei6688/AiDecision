"""按会话投递服务端主动事件的通用 WebSocket 通道。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket


logger = logging.getLogger(__name__)


@dataclass(eq=False)
class WebSocketConnection:
    websocket: WebSocket
    session_ids: set[str] = field(default_factory=set)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class WebSocketPushManager:
    """维护在线连接，并将插件事件投递到指定业务会话。"""

    def __init__(self) -> None:
        self._connections: set[WebSocketConnection] = set()
        self._by_websocket: dict[WebSocket, WebSocketConnection] = {}

    def register(self, websocket: WebSocket) -> WebSocketConnection:
        connection = WebSocketConnection(websocket=websocket)
        self._connections.add(connection)
        self._by_websocket[websocket] = connection
        return connection

    def unregister(self, connection: WebSocketConnection) -> None:
        self._connections.discard(connection)
        self._by_websocket.pop(connection.websocket, None)

    def bind_session(self, connection: WebSocketConnection, session_id: str) -> None:
        connection.session_ids.add(session_id)

    async def send_to_session(self, session_id: str, event: dict[str, Any]) -> int:
        delivered = 0
        for connection in list(self._connections):
            if session_id not in connection.session_ids:
                continue
            try:
                await self._send(connection, event)
                delivered += 1
            except Exception:
                logger.exception("WebSocket 主动推送失败: session_id=%s", session_id)
                self.unregister(connection)
        return delivered

    async def send_raw(self, websocket: WebSocket, event: dict[str, Any]) -> None:
        connection = self._by_websocket.get(websocket)
        if connection is None:
            await websocket.send_json(event)
            return
        await self._send(connection, event)

    @staticmethod
    async def _send(connection: WebSocketConnection, event: dict[str, Any]) -> None:
        async with connection.lock:
            await connection.websocket.send_json(event)
