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
    "photo_storage_type": "photoStorageType",
    "pano_shot": "panoShot",
    "is_record": "isRecord",
    "is_terrain": "isTerrain",
}


def _to_api_payload(params: dict[str, Any]) -> dict[str, Any]:
    """Translate normalized Pydantic names to the legacy inspection API contract."""

    return {_API_FIELD_NAMES.get(key, key): value for key, value in params.items()}
