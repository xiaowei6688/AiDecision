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
    if not settings.auth_enabled:
        return AuthContext(
            user_id=user_id or "anonymous-user",
            tenant_id=tenant_id or "anonymous-tenant",
            roles=tuple(r.strip() for r in (roles_header or "").split(",") if r.strip()),
        )

    # 实际部署应替换为 JWT/SSO 校验；这些请求头仅允许在开发环境中使用。
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
    # Token 校验方式取决于部署环境；配置校验器前不得将其内容视为身份信息。
    if http:
        raise HTTPException(status_code=501, detail="Bearer token verifier is not configured")
    raise ValueError("Bearer token verifier is not configured")
