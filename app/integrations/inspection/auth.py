"""AllCore authentication helpers for the inspection integration."""

from __future__ import annotations

import asyncio
from functools import lru_cache
import logging
import threading
import time
from typing import Any

import httpx

from app.integrations.inspection.config import InspectionSettings, get_inspection_settings


class InspectionAuthError(RuntimeError):
    """Raised when the inspection upstream auth header cannot be built."""


logger = logging.getLogger(__name__)


class InspectionAuthClient:
    def __init__(self, settings: InspectionSettings | None = None) -> None:
        self._settings = settings or get_inspection_settings()
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._refreshing = False

    async def headers(self) -> dict[str, str]:
        return await asyncio.to_thread(self.headers_sync)

    def headers_sync(self) -> dict[str, str]:
        auth_header = self.allcore_auth_header_sync()
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "allcore-auth": auth_header,
        }
        if self._settings.basic_auth:
            headers["Authorization"] = normalize_basic_auth(self._settings.basic_auth)
        if self._settings.tenant_id:
            headers["Tenant-Id"] = self._settings.tenant_id
        return headers

    async def allcore_auth_header(self) -> str:
        return await asyncio.to_thread(self.allcore_auth_header_sync)

    def allcore_auth_header_sync(self) -> str:
        if self._settings.auth_token:
            return normalize_bearer_token(self._settings.auth_token)

        now = time.time()
        refresh_before = self._settings.token_refresh_before_seconds
        with self._lock:
            if self._access_token and now < self._expires_at - refresh_before:
                return normalize_bearer_token(self._access_token)
            if self._access_token and self._refreshing:
                return normalize_bearer_token(self._access_token)
            self._refreshing = True

        try:
            access_token = self._request_access_token_sync()
            with self._lock:
                self._access_token = access_token
                self._expires_at = now + self._settings.token_ttl_seconds
                self._refreshing = False
            return normalize_bearer_token(access_token)
        except Exception:
            with self._lock:
                self._refreshing = False
            raise

    async def refresh(self) -> str | None:
        return await asyncio.to_thread(self.refresh_sync)

    def refresh_sync(self) -> str | None:
        if self._settings.auth_token:
            logger.info("Inspection static token configured, refresh skipped")
            return None

        now = time.time()
        refresh_before = self._settings.token_refresh_before_seconds
        with self._lock:
            if self._access_token and now < self._expires_at - refresh_before:
                return None
            if self._refreshing:
                return None
            self._refreshing = True

        try:
            access_token = self._request_access_token_sync()
            with self._lock:
                self._access_token = access_token
                self._expires_at = now + self._settings.token_ttl_seconds
                self._refreshing = False
            return access_token
        except Exception:
            with self._lock:
                self._refreshing = False
            raise

    async def reset(self) -> None:
        await asyncio.to_thread(self.reset_sync)

    def reset_sync(self) -> None:
        with self._lock:
            self._access_token = None
            self._expires_at = 0
            self._refreshing = False

    def has_static_token(self) -> bool:
        return bool(self._settings.auth_token)

    def missing_login_fields(self) -> list[str]:
        settings = self._settings
        return [
            name
            for name, value in {
                "inspection_auth_login_url": settings.auth_login_url,
                "inspection_auth_username": settings.auth_username,
                "inspection_auth_password": settings.auth_password,
                "inspection_basic_auth": settings.basic_auth,
                "inspection_tenant_id": settings.tenant_id,
            }.items()
            if not value
        ]

    def refresh_interval_seconds(self) -> int:
        return max(self._settings.token_ttl_seconds - self._settings.token_refresh_before_seconds, 60)

    def _request_access_token_sync(self) -> str:
        settings = self._settings
        missing = self.missing_login_fields()
        if missing:
            raise InspectionAuthError(f"缺少巡检 AllCore 登录配置：{', '.join(missing)}")

        params = {
            "tenantId": settings.tenant_id,
            "username": settings.auth_username,
            "password": settings.auth_password,
            "grant_type": settings.auth_grant_type,
            "type": settings.auth_type,
            "scope": settings.auth_scope,
        }
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": normalize_basic_auth(settings.basic_auth or ""),
            "Content-Type": "application/x-www-form-urlencoded",
            "Tenant-Id": settings.tenant_id or "",
            "allcore-Auth": "bearer",
        }
        try:
            response = httpx.post(
                str(settings.auth_login_url),
                params=params,
                headers=headers,
                timeout=settings.api_timeout_seconds,
                verify=False,
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


@lru_cache
def get_inspection_auth_client() -> InspectionAuthClient:
    return InspectionAuthClient()
