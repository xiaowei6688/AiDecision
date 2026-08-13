"""AllCore authentication helpers for the inspection integration."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.core.config import Settings


class InspectionAuthError(RuntimeError):
    """Raised when the inspection upstream auth header cannot be built."""


class InspectionAuthClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = asyncio.Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._refreshing = False

    async def headers(self) -> dict[str, str]:
        auth_header = await self.allcore_auth_header()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "allcore-auth": auth_header,
        }
        if self._settings.inspection_basic_auth:
            headers["Authorization"] = normalize_basic_auth(self._settings.inspection_basic_auth)
        if self._settings.inspection_tenant_id:
            headers["Tenant-Id"] = self._settings.inspection_tenant_id
        return headers

    async def allcore_auth_header(self) -> str:
        if self._settings.inspection_auth_token:
            return normalize_bearer_token(self._settings.inspection_auth_token)

        now = time.time()
        refresh_before = self._settings.inspection_token_refresh_before_seconds
        async with self._lock:
            if self._access_token and now < self._expires_at - refresh_before:
                return normalize_bearer_token(self._access_token)
            if self._access_token and self._refreshing:
                return normalize_bearer_token(self._access_token)
            self._refreshing = True

        try:
            access_token = await self._request_access_token()
            async with self._lock:
                self._access_token = access_token
                self._expires_at = now + self._settings.inspection_token_ttl_seconds
                self._refreshing = False
            return normalize_bearer_token(access_token)
        except Exception:
            async with self._lock:
                self._refreshing = False
            raise

    async def reset(self) -> None:
        async with self._lock:
            self._access_token = None
            self._expires_at = 0
            self._refreshing = False

    async def _request_access_token(self) -> str:
        settings = self._settings
        missing = [
            name
            for name, value in {
                "inspection_auth_login_url": settings.inspection_auth_login_url,
                "inspection_auth_username": settings.inspection_auth_username,
                "inspection_auth_password": settings.inspection_auth_password,
                "inspection_basic_auth": settings.inspection_basic_auth,
                "inspection_tenant_id": settings.inspection_tenant_id,
            }.items()
            if not value
        ]
        if missing:
            raise InspectionAuthError(f"缺少巡检 AllCore 登录配置：{', '.join(missing)}")

        params = {
            "tenantId": settings.inspection_tenant_id,
            "username": settings.inspection_auth_username,
            "password": settings.inspection_auth_password,
            "grant_type": settings.inspection_auth_grant_type,
            "type": settings.inspection_auth_type,
            "scope": settings.inspection_auth_scope,
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": normalize_basic_auth(settings.inspection_basic_auth or ""),
            "Content-Type": "application/x-www-form-urlencoded",
            "Tenant-Id": settings.inspection_tenant_id or "",
            "allcore-Auth": "bearer",
        }
        async with httpx.AsyncClient(timeout=settings.inspection_api_timeout_seconds, verify=False) as client:
            try:
                response = await client.post(
                    str(settings.inspection_auth_login_url),
                    params=params,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise InspectionAuthError(
                    f"巡检 AllCore 登录失败，状态码 {exc.response.status_code}: {exc.response.text}"
                ) from exc
            except httpx.RequestError as exc:
                raise InspectionAuthError(f"巡检 AllCore 登录请求异常: {exc}") from exc

        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise InspectionAuthError(f"巡检 AllCore 登录响应不是 JSON: {response.text}") from exc
        access_token = payload.get("access_token") if isinstance(payload, dict) else None
        if not access_token:
            raise InspectionAuthError("巡检 AllCore 登录响应缺少 access_token")
        return str(access_token)


def normalize_bearer_token(token: str) -> str:
    normalized = token.strip()
    if normalized and not normalized.lower().startswith("bearer "):
        normalized = f"bearer {normalized}"
    return normalized


def normalize_basic_auth(auth_value: str) -> str:
    normalized = auth_value.strip()
    if normalized and not normalized.lower().startswith("basic "):
        normalized = f"Basic {normalized}"
    return normalized
