import pytest

from app.integrations.inspection.websocket_actions import inspection_work_order_action_result_to_resume
from app.integrations.websocket_actions import (
    action_result_to_resume_request,
    clear_action_result_handlers,
    register_action_result_handler,
)
from app.schemas.chat import WebSocketClientEvent, ClientEventType


def test_action_result_to_resume_request_rejects_without_registered_handler() -> None:
    clear_action_result_handlers()
    event = WebSocketClientEvent(
        type=ClientEventType.ACTION_RESULT,
        action_code="demoAction",
        action_result={"status": "success", "message": "ok", "data": {"id": 1}},
    )

    with pytest.raises(ValueError, match="当前业务不支持 actionResult 回执"):
        action_result_to_resume_request(event)


def test_action_result_to_resume_request_uses_inspection_work_order_handler() -> None:
    clear_action_result_handlers()
    register_action_result_handler(inspection_work_order_action_result_to_resume)
    event = WebSocketClientEvent(
        type=ClientEventType.ACTION_RESULT,
        action_code="createTempOrder",
        action_result={"status": "success", "message": "ok", "data": {"id": 1}},
    )

    request = action_result_to_resume_request(event)

    assert request.action == "approve"
    assert request.content == "ok"
    assert request.data["actionCode"] == "createTempOrder"
