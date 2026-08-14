"""Inspection-specific UI compatibility projections."""

from __future__ import annotations

from typing import Any

from app.actions.schemas import ActionResult


def inspection_action_result_projection(result: ActionResult) -> dict[str, object]:
    if result.status != "requires_confirmation":
        return {}
    action = result.data.get("action")
    params = result.data.get("params")
    if not isinstance(action, dict) or not isinstance(params, dict):
        return {}
    action_id = result.action_id
    if action_id == "inspection.create_plan":
        action_code = "createPlan"
        route_path = "/plan/review"
        execute_api = "/plan/create"
        question = "请确认是否创建以下巡检计划"
    elif action_id == "inspection.create_work_order":
        action_code = "createTempOrder"
        route_path = "/workOrder/review"
        execute_api = "/order/createTempOrder"
        question = "请确认是否创建以下巡检工单"
    else:
        return {}
    return {
        "question": question,
        "businessId": "inspection",
        "actionCode": action_code,
        "routePath": route_path,
        "executeApi": execute_api,
        "executeMethod": "POST",
        "executePayload": params,
        "displayFields": _display_fields(action_id, params),
    }


def inspection_human_interrupt_projection(interrupts: list[object]) -> dict[str, object]:
    if not interrupts:
        return {}
    first = interrupts[0]
    if not isinstance(first, dict):
        return {}
    payload = first.get("payload")
    if not isinstance(payload, dict) or payload.get("businessId") != "inspection":
        return {}
    flattened = {**first, **payload}
    return {
        "content": first.get("question"),
        "data": {
            **payload,
            "interrupts": [flattened],
        },
    }


def _display_fields(action_id: str, params: dict[str, Any]) -> dict[str, Any]:
    if action_id == "inspection.create_plan":
        return {
            "planName": params.get("plan_name", params.get("planName")),
            "planType": params.get("plan_type", params.get("planType")),
            "inspectStartTime": params.get("inspect_start_time", params.get("inspectStartTime")),
            "inspectEndTime": params.get("inspect_end_time", params.get("inspectEndTime")),
            "planObjectListNames": [
                item.get("deviceName") or item.get("device_name")
                for item in params.get("plan_object_list", params.get("planObjectList", []))
                if isinstance(item, dict) and (item.get("deviceName") or item.get("device_name"))
            ],
        }
    return {
        "planGuid": params.get("plan_guid", params.get("planGuid")),
        "inspectionMethod": params.get("inspection_method", params.get("inspectionMethod")),
        "startDate": params.get("start_date", params.get("startDate")),
        "endDate": params.get("end_date", params.get("endDate")),
    }
