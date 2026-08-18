from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RequestRuntimeContext:
    """无需模型控制参数即可提供给工具的可信请求事实。"""

    user_id: str | None = None
    user_roles: tuple[str, ...] = ()
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    plugin_context: Any = None


_runtime_context: ContextVar[RequestRuntimeContext] = ContextVar(
    "request_runtime_context",
    default=RequestRuntimeContext(),
)


def get_runtime_context() -> RequestRuntimeContext:
    return _runtime_context.get()


def set_runtime_context(context: RequestRuntimeContext) -> Token[RequestRuntimeContext]:
    return _runtime_context.set(context)


def reset_runtime_context(token: Token[RequestRuntimeContext]) -> None:
    _runtime_context.reset(token)
