from dataclasses import dataclass, field
from typing import Any

from fastapi import HTTPException, Request, WebSocket

from app.core.config import Settings


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    tenant_id: str
    roles: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def authenticate_request(request: Request, settings: Settings) -> AuthContext:
    return _authenticate(
        settings,
        request.headers.get("authorization"),
        request.headers.get("x-user-id"),
        request.headers.get("x-tenant-id"),
        request.headers.get("x-user-roles"),
        http=True,
    )


def authenticate_websocket(websocket: WebSocket, settings: Settings) -> AuthContext:
    return _authenticate(
        settings,
        websocket.headers.get("authorization"),
        websocket.headers.get("x-user-id"),
        websocket.headers.get("x-tenant-id"),
        websocket.headers.get("x-user-roles"),
        http=False,
    )


def _authenticate(
    settings: Settings,
    authorization: str | None,
    user_id: str | None,
    tenant_id: str | None,
    roles_header: str | None,
    *,
    http: bool,
) -> AuthContext:
    # A real deployment should replace this with JWT/SSO verification. These
    # headers are intentionally accepted only in development.
    if settings.environment == "development" and not authorization:
        return AuthContext(
            user_id=user_id or "dev-user",
            tenant_id=tenant_id or "dev-tenant",
            roles=tuple(r.strip() for r in (roles_header or "").split(",") if r.strip()),
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        if http:
            raise HTTPException(status_code=401, detail="Authentication required")
        raise ValueError("Authentication required")
    # Token verification is deployment-specific; do not treat its contents as
    # identity until a verifier is configured.
    if http:
        raise HTTPException(status_code=501, detail="Bearer token verifier is not configured")
    raise ValueError("Bearer token verifier is not configured")
