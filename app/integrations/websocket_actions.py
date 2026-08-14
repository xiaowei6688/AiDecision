"""Integration-registered WebSocket action-result translation helpers."""

from __future__ import annotations

from collections.abc import Callable

from app.schemas.chat import HumanResumeRequest, WebSocketClientEvent


ActionResultHandler = Callable[[WebSocketClientEvent], HumanResumeRequest | None]

_action_result_handlers: list[ActionResultHandler] = []


def register_action_result_handler(handler: ActionResultHandler) -> None:
    if handler in _action_result_handlers:
        return
    _action_result_handlers.append(handler)


def clear_action_result_handlers() -> None:
    _action_result_handlers.clear()


def action_result_to_resume_request(client_event: WebSocketClientEvent) -> HumanResumeRequest:
    for handler in _action_result_handlers:
        request = handler(client_event)
        if request is not None:
            return request
    raise ValueError("当前业务不支持 actionResult 回执")
