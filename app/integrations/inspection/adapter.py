"""Adapter for inspection actions handed off to the legacy frontend."""

from typing import Any

from app.actions.schemas import ActionExecutionContext


class InspectionAdapter:
    async def invoke(
        self,
        method: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        contract = _FRONTEND_ACTIONS.get(method)
        if contract is None:
            raise ValueError(f"Unsupported inspection operation: {method}")
        payload = _to_api_payload(params)
        return {
            **contract,
            "executePayload": payload,
            "executionMode": "frontend_callback",
            "sessionId": context.session_id,
        }


_FRONTEND_ACTIONS = {
    "create_plan": {
        "actionCode": "createPlan",
        "routePath": "/plan/review",
        "executeApi": "/plan/create",
        "executeMethod": "POST",
    },
    "create_work_order": {
        "actionCode": "createTempOrder",
        "routePath": "/workOrder/review",
        "executeApi": "/order/createTempOrder",
        "executeMethod": "POST",
    },
    "fly_work_order": {
        "actionCode": "flyWorkOrder",
        "routePath": "/workOrder/review",
        "executeApi": "/order/fly",
        "executeMethod": "POST",
    },
}


_API_FIELD_NAMES = {
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
    "other_workers": "otherWorkers",
    "drone_list": "droneList",
    "photo_storage_type": "photoStorageType",
    "pano_shot": "panoShot",
    "is_record": "isRecord",
    "is_terrain": "isTerrain",
    "work_cycle_type": "workCycleType",
    "cycle_start_date": "cycleStartDate",
    "cycle_end_date": "cycleEndDate",
    "cycle_inspect_start_time": "cycleInspectStartTime",
    "cycle_inspect_end_time": "cycleInspectEndTime",
    "day_dates": "dayDates",
    "week_days": "weekDays",
    "month_days": "monthDays",
    "year_dates": "yearDates",
}


def _to_api_payload(params: dict[str, Any]) -> dict[str, Any]:
    """Translate normalized Pydantic names to the legacy inspection API contract."""

    return {
        _API_FIELD_NAMES.get(key, key): value
        for key, value in params.items()
        if key not in {"final_summary", "finalSummary"}
        and not (key in _CYCLE_FIELD_NAMES and value is None)
    }


_CYCLE_FIELD_NAMES = {
    "work_cycle_type",
    "cycle_start_date",
    "cycle_end_date",
    "cycle_inspect_start_time",
    "cycle_inspect_end_time",
    "day_dates",
    "week_days",
    "month_days",
    "year_dates",
}
