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
    async def get_session_history(
        self,
        _session_id: str,
        **_filters: Any,
    ) -> list[dict[str, Any]]:
        return [
            {
                "message_id": "message-1",
                "type": "human",
                "role": "user",
                "content": "查询巡检计划",
                "metadata": {"request_id": "request-1", "timestamp": "2026-08-19T10:00:00Z"},
            },
            {
                "message_id": "message-2",
                "type": "ai",
                "role": "assistant",
                "content": "请提供线路名称",
                "metadata": {"parent_message_id": "message-1"},
            },
        ]

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


def test_session_history_includes_legacy_projection() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.get("/sessions/demo/history")

    assert response.status_code == 200
    body = response.json()
    assert body["history"][0]["role"] == "user"
    assert body["code"] == 200
    assert body["data"]["session_id"] == "demo"
    legacy_messages = body["data"]["history"][0]["messages"]
    assert legacy_messages[0]["role"] == "human"
    assert legacy_messages[0]["request_id"] == "request-1"
    assert legacy_messages[1]["role"] == "ai"
    assert legacy_messages[1]["parent_message_id"] == "message-1"


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


def test_legacy_chat_endpoint_uses_session_id_from_body() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post(
            "/chat",
            json={
                "type": "message",
                "content": "可以",
                "session_id": "legacy-session",
                "metadata": {"source": "legacy"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["event"]["session_id"] == "legacy-session"
    assert body["event"]["content"] == "echo: 可以"


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
            websocket.send_json({
                "type": "message",
                "session_id": "demo",
                "content": "hello",
            })

            message = websocket.receive_json()

    assert message["type"] == "message"
    assert message["content"] == "echo: hello"


def test_chat_websocket_rejects_event_without_session_id() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/demo") as websocket:
            websocket.receive_json()
            websocket.send_json({"type": "message", "content": "hello"})
            error = websocket.receive_json()

    assert error["type"] == "error"
    assert error["data"]["code"] == "invalid_payload"


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


def test_legacy_websocket_alias_creates_session() -> None:
    app = create_app(
        settings=Settings(_env_file=None, auth_enabled=False),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
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
                    "session_id": "demo",
                    "resume": {
                        "action": "clarify",
                        "content": "会议主题是 Q3 产品规划",
                        "data": {"duration_minutes": 60},
                    },
                }
            )

            websocket.send_json({
                "type": "ping",
                "session_id": "demo",
                "request_id": "after-resume",
            })
            pong = websocket.receive_json()

    assert pong["type"] == "pong"
    assert pong["request_id"] == "after-resume"


def test_chat_websocket_runs_plugin_continuation_after_action_result() -> None:
    app = create_app(
        settings=Settings(
            _env_file=None,
            auth_enabled=False,
            enabled_integrations=["inspection"],
        ),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/demo") as websocket:
            websocket.receive_json()
            websocket.send_json({
                "content": "",
                "role": "human",
                "type": "actionResult",
                "request_id": "request-1",
                "message_id": "message-1",
                "action_result": {
                    "action_code": "createPlan",
                    "content": None,
                    "data": {
                        "code": 200,
                        "success": True,
                        "data": "357520855904816740",
                        "msg": "操作成功",
                    },
                },
                "session_id": "demo",
            })

            event = websocket.receive_json()

    continuation = event["data"]["metadata"]["business_continuation"]
    assert event["type"] == "message"
    assert event["request_id"] == "request-1"
    assert event["parent_message_id"] == "message-1"
    assert continuation == {
        "businessId": "inspection",
        "operation": "create_work_orders_from_plan",
        "planId": "357520855904816740",
    }
    assert "请说明" not in event["content"]


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


def test_inspection_notifications_push_to_the_bound_websocket_session() -> None:
    app = create_app(
        settings=Settings(
            _env_file=None,
            auth_enabled=False,
            enabled_integrations=["inspection"],
        ),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/demo") as websocket:
            websocket.receive_json()
            response = client.post(
                "/notify/start_flying",
                json={
                    "type": "startFlying",
                    "content": {
                        "workOrderId": "order-1",
                        "workOrderNo": "AL-001",
                        "dockSn": "dock-1",
                        "droneSn": "drone-1",
                        "relationSessionId": "demo",
                    },
                },
            )
            event = websocket.receive_json()

    assert response.status_code == 200
    assert response.json()["delivered"] == 1
    assert event["type"] == "human_action_required"
    assert event["session_id"] == "demo"
    assert event["data"]["interrupts"][0]["actionCode"] == "flightMonitoring"


def test_inspection_defect_notification_keeps_real_counts() -> None:
    app = create_app(
        settings=Settings(
            _env_file=None,
            auth_enabled=False,
            enabled_integrations=["inspection"],
        ),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/demo") as websocket:
            websocket.receive_json()
            response = client.post(
                "/integrations/inspection/notify",
                json={
                    "type": "recognizeCompleted",
                    "content": {
                        "workOrderId": "order-1",
                        "workOrderNo": "AL-001",
                        "recognitionTaskGuid": "task-1",
                        "taskName": "白路线缺陷识别任务",
                        "relationSessionId": "demo",
                        "totalPictures": 20,
                        "defectPictures": 4,
                        "totalDefects": 5,
                        "normalDefects": 3,
                        "seriousDefects": 1,
                        "criticalDefects": 1,
                    },
                },
            )
            event = websocket.receive_json()

    assert response.status_code == 200
    assert response.json()["delivered"] == 1
    assert "共识别缺陷 5 处" in event["content"]
    assert "严重缺陷：1 处" in event["content"]
    action = event["data"]["interrupts"][0]
    assert action["actionCode"] == "openRecognitionTask"
    assert action["executePayload"] == {
        "recognitionTaskGuid": "task-1",
        "workOrderNo": "AL-001",
    }


def test_start_flying_notification_resolves_session_from_work_order_binding() -> None:
    from app.integrations.inspection.bindings import inspection_session_bindings

    inspection_session_bindings.bind_work_order("order-bound", "demo")
    app = create_app(
        settings=Settings(
            _env_file=None,
            auth_enabled=False,
            enabled_integrations=["inspection"],
        ),
        session_service=FakeSessionService(),
    )  # type: ignore[arg-type]

    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat/demo") as websocket:
            websocket.receive_json()
            response = client.post(
                "/integrations/inspection/notify",
                json={
                    "type": "startFlying",
                    "content": {
                        "workOrderId": "order-bound",
                        "workOrderNo": "AL-BOUND",
                        "dockSn": "dock-1",
                        "droneSn": "drone-1",
                    },
                },
            )
            event = websocket.receive_json()

    assert response.json()["delivered"] == 1
    assert event["session_id"] == "demo"
