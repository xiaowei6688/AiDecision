import pytest

from app.integrations.inspection.websocket_actions import inspection_action_result_to_resume
from app.integrations.websocket_actions import (
    ActionResultHandlerRegistry,
)
from app.schemas.chat import WebSocketClientEvent, ClientEventType


def test_action_result_to_resume_request_rejects_without_registered_handler() -> None:
    registry = ActionResultHandlerRegistry()
    event = WebSocketClientEvent(
        type=ClientEventType.ACTION_RESULT,
        session_id="session-1",
        action_code="demoAction",
        action_result={"status": "success", "message": "ok", "data": {"id": 1}},
    )

    with pytest.raises(ValueError, match="当前业务不支持 actionResult 回执"):
        registry.to_resume_request(event)


def test_action_result_to_resume_request_uses_inspection_work_order_handler() -> None:
    registry = ActionResultHandlerRegistry()
    registry.register(inspection_action_result_to_resume)
    event = WebSocketClientEvent(
        type=ClientEventType.ACTION_RESULT,
        session_id="session-1",
        action_code="createTempOrder",
        action_result={"status": "success", "message": "ok", "data": {"id": 1}},
    )

    request = registry.to_resume_request(event)

    assert request.action == "approve"
    assert request.content == "ok"
    assert request.data["actionCode"] == "createTempOrder"


def test_inspection_create_plan_accepts_legacy_nested_action_result() -> None:
    registry = ActionResultHandlerRegistry()
    registry.register(inspection_action_result_to_resume)
    event = WebSocketClientEvent.model_validate({
        "type": "actionResult",
        "session_id": "session-1",
        "content": "",
        "role": "human",
        "request_id": "",
        "message_id": "",
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
    })

    request = registry.to_resume_request(event)

    assert request.action == "approve"
    assert request.content == "操作成功"
    assert request.data["actionCode"] == "createPlan"
    assert request.data["planId"] == "357520855904816740"
    assert request.data["businessResult"]["code"] == 200
    assert request.data["businessContinuation"] == {
        "businessId": "inspection",
        "operation": "create_work_orders_from_plan",
        "planId": "357520855904816740",
    }


def test_inspection_work_order_extracts_id_from_legacy_nested_action_result() -> None:
    event = WebSocketClientEvent.model_validate({
        "type": "actionResult",
        "session_id": "session-1",
        "action_result": {
            "action_code": "createTempOrder",
            "data": {
                "code": 200,
                "success": True,
                "data": "order-1",
                "msg": "操作成功",
            },
        },
    })

    request = inspection_action_result_to_resume(event)

    assert request is not None
    assert request.action == "approve"
    assert request.data["workOrderId"] == "order-1"
    assert request.data["businessContinuation"]["operation"] == (
        "verify_work_order_and_continue"
    )


def test_inspection_action_result_prefers_current_nested_action_code() -> None:
    event = WebSocketClientEvent.model_validate({
        "type": "actionResult",
        "session_id": "session-1",
        # 模拟旧前端复用请求对象时残留的上一轮动作码。
        "action_code": "createPlan",
        "action_result": {
            "action_code": "createTempOrder",
            "data": {
                "code": 200,
                "success": True,
                "data": "order-2",
            },
        },
    })

    request = inspection_action_result_to_resume(event)

    assert request is not None
    assert request.data["actionCode"] == "createTempOrder"
    assert request.data["workOrderId"] == "order-2"
    assert request.data["businessContinuation"]["operation"] == (
        "verify_work_order_and_continue"
    )


def test_inspection_action_result_does_not_treat_false_string_as_success() -> None:
    event = WebSocketClientEvent.model_validate({
        "type": "actionResult",
        "session_id": "session-1",
        "action_result": {
            "action_code": "createPlan",
            "data": {"success": "false", "msg": "操作失败"},
        },
    })

    request = inspection_action_result_to_resume(event)

    assert request is not None
    assert request.action == "reject"
