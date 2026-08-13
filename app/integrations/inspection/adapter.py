"""Adapter for the real inspection application API."""

from typing import Any

import httpx

from app.actions.schemas import ActionExecutionContext
from app.core.config import Settings, get_settings
from app.integrations.inspection.auth import InspectionAuthClient


class InspectionAdapter:
    def __init__(
        self,
        settings: Settings | None = None,
        auth_client: InspectionAuthClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._auth_client = auth_client or InspectionAuthClient(self._settings)

    async def invoke(
        self,
        method: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        base_url = self._settings.inspection_api_base_url
        if not base_url:
            raise RuntimeError("未配置 INSPECTION_API_BASE_URL")
        endpoint = {
            "create_plan": "/plan/create",
            "create_work_order": "/order/createTempOrder",
        }.get(method)
        if endpoint is None:
            raise ValueError(f"Unsupported inspection operation: {method}")
        headers = await self._auth_client.headers()
        idempotency_key = context.metadata.get("idempotency_key")
        if idempotency_key:
            headers["Idempotency-Key"] = str(idempotency_key)
        payload = _to_api_payload(params)
        async with httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=self._settings.inspection_api_timeout_seconds,
        ) as client:
            response = await client.post(endpoint, json=payload, headers=headers)
            if response.status_code == 401:
                await self._auth_client.reset()
                headers = await self._auth_client.headers()
                if idempotency_key:
                    headers["Idempotency-Key"] = str(idempotency_key)
                response = await client.post(endpoint, json=payload, headers=headers)
            response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("巡检系统返回的响应不是 JSON 对象")
        return payload


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
