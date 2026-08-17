from __future__ import annotations

import pytest

from app.integrations.inspection.allcore_auth import InspectionAllCoreAuthClient
from app.integrations.inspection.config import InspectionSettings
from app.integrations.inspection.lifecycle import InspectionLifecycle


def _dynamic_settings() -> InspectionSettings:
    return InspectionSettings(
        _env_file=None,
        allcore_auth_login_url="http://inspection.local/oauth/token",
        allcore_auth_username="user",
        allcore_auth_password="password",
        allcore_basic_auth="client-secret",
        allcore_tenant_id="tenant-1",
        allcore_verify_tls=False,
    )


def test_allcore_static_token_builds_inspection_headers() -> None:
    client = InspectionAllCoreAuthClient(
        InspectionSettings(
            _env_file=None,
            allcore_auth_token="static-token",
            allcore_basic_auth="client-secret",
            allcore_tenant_id="tenant-1",
        )
    )

    assert client.headers_sync() == {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "allcore-auth": "bearer static-token",
        "Authorization": "Basic client-secret",
        "Tenant-Id": "tenant-1",
    }


def test_allcore_dynamic_token_is_logged_in_once_and_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"access_token": "dynamic-token"}

    def post(url: str, **kwargs: object) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("app.integrations.inspection.allcore_auth.httpx.post", post)
    client = InspectionAllCoreAuthClient(_dynamic_settings())

    assert client.auth_header_sync() == "bearer dynamic-token"
    assert client.auth_header_sync() == "bearer dynamic-token"
    assert len(calls) == 1
    assert calls[0]["params"] == {
        "tenantId": "tenant-1",
        "username": "user",
        "password": "password",
        "grant_type": "password",
        "type": "account",
        "scope": "all",
    }
    assert calls[0]["headers"] == {
        "Accept": "application/json, text/plain, */*",
        "Authorization": "Basic client-secret",
        "Content-Type": "application/x-www-form-urlencoded",
        "Tenant-Id": "tenant-1",
        "allcore-Auth": "bearer",
    }


def test_allcore_request_refreshes_and_retries_once_after_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tokens = iter(["first-token", "second-token"])
    client = InspectionAllCoreAuthClient(_dynamic_settings())
    monkeypatch.setattr(client, "_request_access_token_sync", lambda: next(tokens))
    request_headers: list[str] = []

    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    def request(headers: dict[str, str]) -> Response:
        request_headers.append(headers["allcore-auth"])
        return Response(401 if len(request_headers) == 1 else 200)

    response = client.request_with_retry_sync(request)

    assert response.status_code == 200
    assert request_headers == ["bearer first-token", "bearer second-token"]


def test_expired_static_token_falls_back_to_dynamic_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _dynamic_settings().model_copy(update={"allcore_auth_token": "expired-token"})
    client = InspectionAllCoreAuthClient(settings)
    monkeypatch.setattr(client, "_request_access_token_sync", lambda: "fresh-token")
    request_headers: list[str] = []

    class Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    def request(headers: dict[str, str]) -> Response:
        request_headers.append(headers["allcore-auth"])
        return Response(401 if len(request_headers) == 1 else 200)

    response = client.request_with_retry_sync(request)

    assert response.status_code == 200
    assert request_headers == ["bearer expired-token", "bearer fresh-token"]


@pytest.mark.asyncio
async def test_startup_prefetch_prefers_fresh_dynamic_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _dynamic_settings().model_copy(update={"allcore_auth_token": "old-token"})
    client = InspectionAllCoreAuthClient(settings)
    monkeypatch.setattr(client, "_request_access_token_sync", lambda: "startup-token")

    token = await client.prefetch()

    assert token == "bearer startup-token"
    assert client.background_refresh_enabled() is True


@pytest.mark.asyncio
async def test_inspection_lifecycle_skips_auth_when_not_configured() -> None:
    class UnconfiguredAuthClient:
        name = "Inspection AllCore token"

        def is_configured(self) -> bool:
            return False

        async def auth_header(self) -> str:
            raise AssertionError("unconfigured auth must not be called")

    lifecycle = InspectionLifecycle(auth_client=UnconfiguredAuthClient())  # type: ignore[arg-type]

    await lifecycle.startup()
    await lifecycle.shutdown()
