"""由插件持有的确定性业务续接事件处理器。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.integrations.direct_results import DirectResult

if TYPE_CHECKING:
    from app.integrations.context import PluginContext


ContinuationHandler = Callable[
    [dict[str, Any], "PluginContext"],
    Awaitable[DirectResult | None],
]


class ContinuationRegistry:
    """无需模型推理，直接分发插件声明的续接操作。"""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], ContinuationHandler] = {}

    def register(
        self,
        business_id: str,
        operation: str,
        handler: ContinuationHandler,
    ) -> None:
        key = (business_id.strip(), operation.strip())
        if not all(key):
            raise ValueError("business continuation requires business_id and operation")
        if key in self._handlers:
            raise ValueError(f"continuation already registered: {key[0]}.{key[1]}")
        self._handlers[key] = handler

    async def dispatch(
        self,
        continuation: dict[str, Any],
        context: "PluginContext",
    ) -> DirectResult | None:
        business_id = str(continuation.get("businessId") or "").strip()
        operation = str(continuation.get("operation") or "").strip()
        handler = self._handlers.get((business_id, operation))
        return await handler(continuation, context) if handler is not None else None
