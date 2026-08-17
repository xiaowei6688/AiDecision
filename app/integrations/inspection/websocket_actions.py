"""Inspection-owned WebSocket action-result handlers."""

from __future__ import annotations

from typing import Any

from app.schemas.chat import HumanResumeRequest, WebSocketClientEvent


PLAN_ACTION_CODES = {"createPlan", "inspection.create_plan", "create_plan"}
WORK_ORDER_ACTION_CODES = {"createTempOrder", "inspection.create_work_order", "create_work_order"}


def inspection_action_result_to_resume(
    client_event: WebSocketClientEvent,
) -> HumanResumeRequest | None:
    action_result = client_event.action_result or {}
    action_code = _action_code(client_event, action_result)
    if action_code in PLAN_ACTION_CODES:
        normalized_code = "createPlan"
        result_id_name = "planId"
    elif action_code in WORK_ORDER_ACTION_CODES:
        normalized_code = "createTempOrder"
        result_id_name = "workOrderId"
    else:
        return None

    business_result = action_result.get("data")
    business_result = business_result if isinstance(business_result, dict) else {}
    success = _is_success(action_result, business_result)
    result_id = _result_id(business_result.get("data"), result_id_name)
    message = (
        action_result.get("message")
        or action_result.get("content")
        or business_result.get("msg")
        or business_result.get("message")
        or client_event.content
    )
    data = {
        **action_result,
        "actionCode": normalized_code,
        "success": success,
        "businessResult": business_result,
    }
    if result_id not in (None, ""):
        data[result_id_name] = str(result_id)
    if success and result_id not in (None, ""):
        data["businessContinuation"] = {
            "businessId": "inspection",
            "operation": (
                "create_work_orders_from_plan"
                if normalized_code == "createPlan"
                else "verify_work_order_and_continue"
            ),
            result_id_name: str(result_id),
        }
    return HumanResumeRequest(
        action="approve" if success else "reject",
        content=str(message) if message not in (None, "") else None,
        data=data,
    )


def _action_code(client_event: WebSocketClientEvent, action_result: dict[str, Any]) -> str | None:
    value = client_event.action_code or action_result.get("actionCode") or action_result.get("action_code")
    return str(value) if value not in (None, "") else None


def _is_success(
    action_result: dict[str, Any],
    business_result: dict[str, Any],
) -> bool:
    code = business_result.get("code")
    if code not in (None, ""):
        return str(code) == "200"
    if "success" in business_result:
        return _as_bool(business_result["success"])
    if "success" in action_result:
        return _as_bool(action_result["success"])
    return action_result.get("status") == "success"


def _result_id(value: Any, field_name: str) -> Any:
    if not isinstance(value, dict):
        return value
    aliases = (
        ("planId", "id", "planGuid")
        if field_name == "planId"
        else ("workOrderId", "orderId", "id")
    )
    return next((value.get(key) for key in aliases if value.get(key) not in (None, "")), None)


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "success"}
    return bool(value)
