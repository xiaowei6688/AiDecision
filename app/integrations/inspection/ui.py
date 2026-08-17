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
    execute_payload = _legacy_payload(params)
    return {
        "question": question,
        "businessId": "inspection",
        "actionCode": action_code,
        "routePath": route_path,
        "executeApi": execute_api,
        "executeMethod": "POST",
        "executePayload": execute_payload,
        "executionMode": "frontend_callback",
        "confirmation_token": result.data.get("confirmation_token"),
        "displayFields": _display_fields(action_id, execute_payload),
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


def inspection_frontend_callback_resume_projection(
    pending_payload: dict[str, Any],
    resume_value: Any,
) -> dict[str, object]:
    action_id = pending_payload.get("action_id")
    if action_id not in {"inspection.create_plan", "inspection.create_work_order"}:
        return {}
    if not isinstance(resume_value, dict):
        return {}

    action = resume_value.get("action")
    if action != "approve":
        return {}

    data = resume_value.get("data") if isinstance(resume_value.get("data"), dict) else {}
    if action_id == "inspection.create_plan":
        action_result_code = _first_non_empty(data, "actionCode", "action_code")
        if action_result_code != "createPlan":
            return {
                "status": "failed",
                "message": "巡检计划创建结果需要通过 actionResult 回传。",
                "error_code": "ACTION_RESULT_REQUIRED",
                "data": {
                    "pendingAction": pending_payload,
                    "frontendResult": data,
                    "final": False,
                    "nextUserAction": "请在前端完成计划创建后回传 actionResult。",
                },
            }
        plan_id = _first_non_empty(data, "planId", "id", "planGuid", "plan_guid")
        if plan_id is None:
            return {
                "status": "failed",
                "message": "计划创建成功回执中缺少计划 ID。",
                "error_code": "PLAN_ID_REQUIRED",
                "data": {
                    "pendingAction": pending_payload,
                    "frontendResult": data,
                    "final": False,
                },
            }
        message = data.get("message") or resume_value.get("content") or (
            f"巡检计划已创建成功：{plan_id}"
        )
        return {
            "status": "success",
            "message": message,
            "data": {
                "pendingAction": pending_payload,
                "frontendResult": data,
                "createdPlanId": plan_id,
                "final": False,
                "businessContinuation": data.get("businessContinuation") or {
                    "businessId": "inspection",
                    "operation": "create_work_orders_from_plan",
                    "planId": plan_id,
                },
                "nextUserAction": "立即按计划 ID 查询真实计划详情，并按机场覆盖情况拆分巡检工单。",
            },
        }

    action_result_code = _first_non_empty(data, "actionCode", "action_code")
    if action_result_code != "createTempOrder":
        return {
            "status": "failed",
            "message": "巡检工单创建结果需要通过 actionResult 回传。",
            "error_code": "ACTION_RESULT_REQUIRED",
            "data": {
                "pendingAction": pending_payload,
                "frontendResult": data,
                "final": False,
                "nextUserAction": "请在前端完成工单创建后回传 actionResult。",
            },
        }

    message = data.get("message") or resume_value.get("content") or "巡检工单已创建成功。"
    pending_execute_payload = pending_payload.get("executePayload")
    pending_execute_payload = (
        pending_execute_payload if isinstance(pending_execute_payload, dict) else {}
    )
    completed_group = (
        "covered"
        if pending_execute_payload.get("inspectionMethod") == "dock"
        else "uncovered"
        if pending_execute_payload.get("inspectionMethod") == "drone"
        else None
    )
    return {
        "status": "success",
        "message": message,
        "data": {
            "pendingAction": pending_payload,
            "frontendResult": data,
            "createdWorkOrderId": _first_non_empty(data, "workOrderId", "id"),
            "completedWorkOrderGroup": completed_group,
            "final": False,
            "businessContinuation": data.get("businessContinuation"),
            "nextUserAction": "请先校验该工单已真实入库，再决定是否创建下一组工单。",
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


_LEGACY_FIELD_NAMES = {
    "plan_type": "planType",
    "plan_name": "planName",
    "inspect_start_time": "inspectStartTime",
    "inspect_end_time": "inspectEndTime",
    "plan_object_list": "planObjectList",
    "plan_guid": "planGuid",
    "work_nature": "workNature",
    "is_cycle": "isCycle",
    "inspection_method": "inspectionMethod",
    "start_date": "startDate",
    "end_date": "endDate",
    "order_detail_list": "orderDetailList",
    "work_content": "workContent",
    "equip_sn": "equipSn",
    "flight_workers": "flightWorkers",
    "photo_storage_type": "photoStorageType",
    "pano_shot": "panoShot",
    "is_record": "isRecord",
    "is_terrain": "isTerrain",
}


def _legacy_payload(params: dict[str, Any]) -> dict[str, Any]:
    return {_LEGACY_FIELD_NAMES.get(key, key): value for key, value in params.items()}


def _first_non_empty(value: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        if candidate not in (None, ""):
            return str(candidate)
    return None
