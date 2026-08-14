"""Typed WebSocket action-result handlers owned by one plugin context."""

from __future__ import annotations

from collections.abc import Callable

from app.schemas.chat import HumanResumeRequest, WebSocketClientEvent


ActionResultHandler = Callable[[WebSocketClientEvent], HumanResumeRequest | None]


class ActionResultHandlerRegistry:
    def __init__(self) -> None:
        self._handlers: list[ActionResultHandler] = []

    def register(self, handler: ActionResultHandler) -> None:
        if handler not in self._handlers:
            self._handlers.append(handler)

    def to_resume_request(self, client_event: WebSocketClientEvent) -> HumanResumeRequest:
        for handler in self._handlers:
            request = handler(client_event)
            if request is not None:
                return request
        raise ValueError("当前业务不支持 actionResult 回执")

    def __len__(self) -> int:
        return len(self._handlers)
