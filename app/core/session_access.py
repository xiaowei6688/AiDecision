from dataclasses import dataclass
from threading import Lock

from app.core.auth import AuthContext
from app.core.runtime_context import RequestRuntimeContext
from app.core.durable_state import PostgresDurableState


@dataclass(frozen=True)
class SessionOwner:
    user_id: str
    tenant_id: str


class SessionAccessStore:
    """Replaceable ownership store; production should back this with a DB."""

    def __init__(
        self,
        allow_unknown: bool = False,
        durable_state: PostgresDurableState | None = None,
    ) -> None:
        self._owners: dict[str, tuple[SessionOwner, AuthContext]] = {}
        self._allow_unknown = allow_unknown
        self._lock = Lock()
        self._durable_state = durable_state

    async def create(self, session_id: str, auth: AuthContext) -> None:
        if self._durable_state is not None:
            await self._durable_state.create_session(session_id, auth)
        with self._lock:
            self._owners[session_id] = (SessionOwner(auth.user_id, auth.tenant_id), auth)

    async def ensure_access(self, session_id: str, auth: AuthContext) -> None:
        if self._durable_state is not None:
            context = await self._durable_state.session_context(session_id, auth)
            with self._lock:
                self._owners[session_id] = (
                    SessionOwner(context.user_id or "", context.metadata["tenant_id"]), auth
                )
            return
        with self._lock:
            record = self._owners.get(session_id)
            if record is None and self._allow_unknown:
                # Development compatibility for pre-existing checkpoint threads.
                self._owners[session_id] = (SessionOwner(auth.user_id, auth.tenant_id), auth)
                return
            if record is None:
                raise PermissionError("Session does not exist")
            owner, _ = record
            if owner != SessionOwner(auth.user_id, auth.tenant_id):
                raise PermissionError("Session does not belong to the authenticated principal")

    def context(self, session_id: str) -> RequestRuntimeContext:
        with self._lock:
            record = self._owners.get(session_id)
        if record is None:
            return RequestRuntimeContext(session_id=session_id)
        _, auth = record
        return RequestRuntimeContext(
            user_id=auth.user_id,
            user_roles=auth.roles,
            session_id=session_id,
            metadata={"tenant_id": auth.tenant_id, **auth.metadata},
        )

    def list_owned(self, auth: AuthContext) -> list[str]:
        with self._lock:
            return [
                session_id
                for session_id, (owner, _) in self._owners.items()
                if owner == SessionOwner(auth.user_id, auth.tenant_id)
            ]
