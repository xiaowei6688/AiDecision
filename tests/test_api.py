from collections.abc import AsyncIterator
from typing import Any

from fastapi.testclient import TestClient
import pytest

from app.main import create_app
from app.schemas.chat import HumanResumeRequest, SessionStateResponse
from app.core.auth import AuthContext, authenticate_request
from app.core.session_access import SessionAccessStore
from app.core.config import Settings


class FakeSessionService:
    async def send_message_event(
        self,
        session_id: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "message",
            "session_id": session_id,
            "content": f"echo: {message}",
            "data": {"metadata": metadata or {}},
        }

    async def stream_message(
        self,
        session_id: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {
            "type": "message",
            "session_id": session_id,
            "content": f"echo: {message}",
            "data": {"metadata": metadata or {}},
        }

    async def get_state(self, session_id: str) -> SessionStateResponse:
        return SessionStateResponse(
            session_id=session_id,
            exists=True,
            intent="test",
            dialogue_stage="started",
            summary="fake state",
            metadata={"source": "test"},
        )

    async def resume(
        self,
        session_id: str,
        request: HumanResumeRequest,
    ) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "resumed": request.action,
            "content": request.content,
            "data": request.data,
        }

    async def resume_event(
        self,
        session_id: str,
        request: HumanResumeRequest,
    ) -> dict[str, Any]:
        return {
            "type": "dst_state",
            "session_id": session_id,
            "data": await self.resume(session_id, request),
        }


def test_health_endpoint_uses_injected_service() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_authentication_can_be_disabled() -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None, auth_enabled=False)

    class _Request:
        headers = {}

    auth = authenticate_request(_Request(), settings)  # type: ignore[arg-type]

    assert auth.user_id == "anonymous-user"
    assert auth.tenant_id == "anonymous-tenant"


@pytest.mark.asyncio
async def test_session_access_rejects_different_owner() -> None:
    store = SessionAccessStore()
    await store.create("s1", AuthContext(user_id="u1", tenant_id="t1"))
    try:
        await store.ensure_access("s1", AuthContext(user_id="u2", tenant_id="t1"))
    except PermissionError:
        pass
    else:
        raise AssertionError("different owner should be rejected")


def test_session_state_endpoint() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.get("/sessions/demo/state")

    assert response.status_code == 200
    assert response.json()["session_id"] == "demo"
    assert response.json()["intent"] == "test"


def test_create_session_endpoint_returns_session_id() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post("/sessions")

    assert response.status_code == 200
    assert response.json()["session_id"]


def test_http_message_endpoint_returns_event_and_state() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post(
            "/sessions/demo/messages",
            json={
                "message": "hello",
                "metadata": {"source": "http-test"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["event"]["type"] == "message"
    assert body["event"]["content"] == "echo: hello"
    assert body["state"]["session_id"] == "demo"
    assert body["state"]["intent"] == "test"


def test_http_resume_endpoint_returns_event_and_state() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post(
            "/sessions/demo/resume",
            json={
                "action": "approve",
                "content": "同意继续",
                "data": {"approved_by": "tester"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["event"] == {}
    assert body["state"]["session_id"] == "demo"


def test_chat_websocket_returns_message_without_dst_state() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/demo") as websocket:
            ack = websocket.receive_json()
            assert ack["type"] == "ack"
            assert ack["session_id"] == "demo"
            assert ack["data"]["created"] is False
            websocket.send_json({"type": "message", "content": "hello"})

            message = websocket.receive_json()

    assert message["type"] == "message"
    assert message["content"] == "echo: hello"


def test_chat_websocket_without_session_id_creates_session() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as websocket:
            ack = websocket.receive_json()

    assert ack["type"] == "ack"
    assert ack["session_id"]
    assert ack["data"]["created"] is True


def test_chat_websocket_filters_dst_state_resume_event() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/demo") as websocket:
            websocket.receive_json()
            websocket.send_json(
                {
                    "type": "resume",
                    "resume": {
                        "action": "clarify",
                        "content": "会议主题是 Q3 产品规划",
                        "data": {"duration_minutes": 60},
                    },
                }
            )

            websocket.send_json({"type": "ping", "request_id": "after-resume"})
            pong = websocket.receive_json()

    assert pong["type"] == "pong"
    assert pong["request_id"] == "after-resume"


def test_single_connection_routes_to_the_client_selected_session() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        session_id = client.post("/sessions").json()["session_id"]
        with client.websocket_connect("/ws/chat") as websocket:
            websocket.receive_json()
            websocket.send_json({
                "type": "message",
                "session_id": session_id,
                "request_id": "request-1",
                "message_id": "message-1",
                "content": "hello",
            })
            message = websocket.receive_json()

    assert message["session_id"] == session_id
    assert message["request_id"] == "request-1"
    assert message["parent_message_id"] == "message-1"
