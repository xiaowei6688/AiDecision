"""框架执行边界共享的请求级进度事件。"""

from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass(frozen=True)
class ProgressEvent:
    """适用于框架长时间操作的安全、通用生命周期事件。"""

    event_id: str
    session_id: str | None
    source: str
    business_id: str | None
    step_id: str
    title: str
    summary: str
    status: str
    data: dict[str, Any] = field(default_factory=dict)


class ProgressChannel:
    """请求内异步通道；实例不得在不同会话之间共享。"""

    def __init__(self) -> None:
        self._events: asyncio.Queue[ProgressEvent] = asyncio.Queue()

    def publish(
        self,
        *,
        session_id: str | None,
        source: str,
        business_id: str | None,
        step_id: str,
        title: str,
        summary: str,
        status: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        self._events.put_nowait(ProgressEvent(
            event_id=str(uuid4()),
            session_id=session_id,
            source=source,
            business_id=business_id,
            step_id=step_id,
            title=title,
            summary=summary,
            status=status,
            data=dict(data or {}),
        ))

    async def receive(self) -> ProgressEvent:
        return await self._events.get()

    def receive_nowait(self) -> ProgressEvent | None:
        try:
            return self._events.get_nowait()
        except asyncio.QueueEmpty:
            return None


_progress_channel: ContextVar[ProgressChannel | None] = ContextVar(
    "request_progress_channel",
    default=None,
)


def get_progress_channel() -> ProgressChannel | None:
    return _progress_channel.get()


def set_progress_channel(channel: ProgressChannel | None) -> Token[ProgressChannel | None]:
    return _progress_channel.set(channel)


def reset_progress_channel(token: Token[ProgressChannel | None]) -> None:
    _progress_channel.reset(token)
