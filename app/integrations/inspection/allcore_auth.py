"""Inspection-owned AllCore token acquisition and refresh."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import lru_cache
import logging
import threading
import time
from typing import Any, TypeVar

import httpx

from app.integrations.inspection.config import InspectionSettings, get_inspection_settings


logger = logging.getLogger(__name__)
ResponseT = TypeVar("ResponseT")


class InspectionAllCoreAuthError(RuntimeError):
    """Raised when an inspection AllCore token cannot be acquired."""


class InspectionAllCoreAuthClient:
    name = "Inspection AllCore token"

    def __init__(self, settings: InspectionSettings | None = None) -> None:
        self._settings = settings or get_inspection_settings()
        self._lock = threading.Lock()
        self._access_token: str | None = None
        self._expires_at = 0.0
        self._refreshing = False
        self._prefer_dynamic_login = False

    def headers_sync(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "allcore-auth": self.auth_header_sync(),
        }
        if self._settings.allcore_basic_auth:
            headers["Authorization"] = _normalize_basic(
                self._settings.allcore_basic_auth
            )
        if self._settings.allcore_tenant_id:
            headers["Tenant-Id"] = self._settings.allcore_tenant_id
        return headers

    def auth_header_sync(self) -> str:
        static_token = self._settings.allcore_auth_token
        if static_token and not self._prefer_dynamic_login:
            return _normalize_bearer(static_token)

        now = time.time()
        refresh_before = self._settings.allcore_token_refresh_before_seconds
        with self._lock:
            if self._access_token and now < self._expires_at - refresh_before:
                return _normalize_bearer(self._access_token)
            if self._access_token and self._refreshing:
                return _normalize_bearer(self._access_token)
            self._refreshing = True

        try:
            access_token = self._request_access_token_sync()
            with self._lock:
                self._access_token = access_token
                self._expires_at = now + self._settings.allcore_token_ttl_seconds
                self._refreshing = False
            return _normalize_bearer(access_token)
        except Exception:
            with self._lock:
                self._refreshing = False
            raise

    async def auth_header(self) -> str:
        return await asyncio.to_thread(self.auth_header_sync)

    async def prefetch(self) -> str:
        if self._has_dynamic_login_config():
            self._prefer_dynamic_login = True
            self.reset_sync()
        return await self.auth_header()

    def refresh_sync(self, *, force: bool = False) -> str | None:
        if self._settings.allcore_auth_token and not self._prefer_dynamic_login:
            return None
        if force:
            self.reset_sync()
        else:
            now = time.time()
            with self._lock:
                if (
                    self._access_token
                    and now
                    < self._expires_at
                    - self._settings.allcore_token_refresh_before_seconds
                ):
                    return None
                if self._refreshing:
                    return None
        return self.auth_header_sync()

    async def refresh(self, *, force: bool = False) -> str | None:
        return await asyncio.to_thread(self.refresh_sync, force=force)

    def request_with_retry_sync(
        self,
        request: Callable[[dict[str, str]], ResponseT],
    ) -> ResponseT:
        response = request(self.headers_sync())
        if (
            getattr(response, "status_code", None) in {401, 403}
            and self._has_dynamic_login_config()
        ):
            self._prefer_dynamic_login = True
            self.reset_sync()
            response = request(self.headers_sync())
        return response

    def reset_sync(self) -> None:
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0
            self._refreshing = False

    def has_static_token(self) -> bool:
        return bool(self._settings.allcore_auth_token)

    def is_configured(self) -> bool:
        return self.has_static_token() or not self.missing_login_fields()

    def background_refresh_enabled(self) -> bool:
        return self._has_dynamic_login_config()

    def _has_dynamic_login_config(self) -> bool:
        return not self.missing_login_fields()

    def missing_login_fields(self) -> list[str]:
        settings = self._settings
        return [
            name
            for name, value in {
                "inspection_allcore_auth_login_url": settings.allcore_auth_login_url,
                "inspection_allcore_auth_username": settings.allcore_auth_username,
                "inspection_allcore_auth_password": settings.allcore_auth_password,
                "inspection_allcore_basic_auth": settings.allcore_basic_auth,
                "inspection_allcore_tenant_id": settings.allcore_tenant_id,
            }.items()
            if not value
        ]

    def refresh_interval_seconds(self) -> int:
        return max(
            self._settings.allcore_token_ttl_seconds
            - self._settings.allcore_token_refresh_before_seconds,
            60,
        )

    def _request_access_token_sync(self) -> str:
        missing = self.missing_login_fields()
        if missing:
            raise InspectionAllCoreAuthError(
                f"缺少 inspection AllCore 登录配置：{', '.join(missing)}"
            )
        settings = self._settings
        try:
            response = httpx.post(
                str(settings.allcore_auth_login_url),
                params={
                    "tenantId": settings.allcore_tenant_id,
                    "username": settings.allcore_auth_username,
                    "password": settings.allcore_auth_password,
                    "grant_type": settings.allcore_auth_grant_type,
                    "type": settings.allcore_auth_type,
                    "scope": settings.allcore_auth_scope,
                },
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Authorization": _normalize_basic(
                        settings.allcore_basic_auth or ""
                    ),
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Tenant-Id": settings.allcore_tenant_id or "",
                    "allcore-Auth": "bearer",
                },
                timeout=settings.api_timeout_seconds,
                verify=settings.allcore_verify_tls,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise InspectionAllCoreAuthError(
                f"inspection AllCore 登录失败：{exc}"
            ) from exc
        try:
            payload: Any = response.json()
        except ValueError as exc:
            raise InspectionAllCoreAuthError(
                "inspection AllCore 登录响应不是 JSON"
            ) from exc
        access_token = payload.get("access_token") if isinstance(payload, dict) else None
        if not access_token:
            raise InspectionAllCoreAuthError(
                "inspection AllCore 登录响应缺少 access_token"
            )
        return str(access_token)


def _normalize_bearer(token: str) -> str:
    value = token.strip()
    return value if value.lower().startswith("bearer ") else f"bearer {value}"


def _normalize_basic(value: str) -> str:
    normalized = value.strip()
    return (
        normalized
        if normalized.lower().startswith("basic ")
        else f"Basic {normalized}"
    )


@lru_cache
def get_inspection_allcore_auth_client() -> InspectionAllCoreAuthClient:
    return InspectionAllCoreAuthClient()
