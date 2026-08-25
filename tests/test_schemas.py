import pytest
from pydantic import ValidationError

from app.schemas.chat import (
    ClientEventType,
    HumanResumeRequest,
    SessionStateResponse,
    WebSocketClientEvent,
)


def test_websocket_client_event_validates_message_payload() -> None:
    event = WebSocketClientEvent.model_validate(
        {
            "type": "message",
            "session_id": "session-1",
            "content": "hello",
            "metadata": {"user_id": "u1"},
        }
    )

    assert event.type == ClientEventType.MESSAGE
    assert event.content == "hello"
    assert event.metadata["user_id"] == "u1"


def test_websocket_client_event_requires_session_id() -> None:
    with pytest.raises(ValidationError):
        WebSocketClientEvent.model_validate({
            "type": "message",
            "content": "hello",
        })


def test_session_state_exposes_generic_domain_state() -> None:
    state = SessionStateResponse(
        session_id="demo",
        exists=True,
        domain_state={
            "inspection": {
                "workOrderFillState": {
                    "status": "READY",
                },
            },
        },
    )

    assert state.domain_state["inspection"]["workOrderFillState"]["status"] == "READY"


def test_human_resume_accepts_frontend_defined_action() -> None:
    request = HumanResumeRequest.model_validate({"action": "flyMonitor"})

    assert request.action == "flyMonitor"
