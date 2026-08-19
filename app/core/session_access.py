from threading import Lock

from app.core.runtime_context import RequestRuntimeContext
from app.core.durable_state import PostgresDurableState


class SessionRegistry:
    """会话注册表，只以 session_id 作为访问与运行时边界。"""

    def __init__(
        self,
        allow_unknown: bool = False,
        durable_state: PostgresDurableState | None = None,
    ) -> None:
        self._sessions: set[str] = set()
        self._allow_unknown = allow_unknown
        self._lock = Lock()
        self._durable_state = durable_state

    async def create(self, session_id: str) -> None:
        if self._durable_state is not None:
            await self._durable_state.create_session(session_id)
        with self._lock:
            self._sessions.add(session_id)

    async def ensure_exists(self, session_id: str) -> None:
        if self._durable_state is not None:
            exists = await self._durable_state.session_exists(session_id)
            if not exists:
                raise LookupError("Session does not exist")
            with self._lock:
                self._sessions.add(session_id)
            return
        with self._lock:
            if session_id not in self._sessions and self._allow_unknown:
                # 开发环境兼容已有的检查点会话。
                self._sessions.add(session_id)
                return
            if session_id not in self._sessions:
                raise LookupError("Session does not exist")

    def context(self, session_id: str) -> RequestRuntimeContext:
        return RequestRuntimeContext(session_id=session_id)

    def list_sessions(self) -> list[str]:
        with self._lock:
            return sorted(self._sessions)
