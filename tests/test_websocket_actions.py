from app.integrations.websocket_actions import action_result_to_resume_request
from app.schemas.chat import WebSocketClientEvent, ClientEventType


def test_action_result_to_resume_request_maps_success_to_approve() -> None:
    event = WebSocketClientEvent(
        type=ClientEventType.ACTION_RESULT,
        action_code="demoAction",
        action_result={"status": "success", "message": "ok", "data": {"id": 1}},
    )

    request = action_result_to_resume_request(event)

    assert request.action == "approve"
    assert request.content == "ok"
    assert request.data["actionCode"] == "demoAction"


def test_action_result_to_resume_request_maps_failure_to_reject() -> None:
    event = WebSocketClientEvent(
        type=ClientEventType.ACTION_RESULT,
        action_result={"status": "failed", "message": "nope"},
    )

    request = action_result_to_resume_request(event)

    assert request.action == "reject"
    assert request.content == "nope"
