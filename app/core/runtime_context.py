from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RequestRuntimeContext:
    """Trusted request facts made available to tools without model-controlled args."""

    user_id: str | None = None
    user_roles: tuple[str, ...] = ()
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


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
