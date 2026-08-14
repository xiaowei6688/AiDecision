"""Inspection-specific read and planning workflows migrated from the legacy service."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import tool

from app.adapters.text_to_sql import TextToSqlClient
from app.core.config import get_settings
from app.integrations.inspection.auth import InspectionAuthError, get_inspection_auth_client
from app.integrations.inspection.config import get_inspection_settings


PLAN_TYPES = {
    "1": "年计划",
    "2": "月计划",
    "3": "周计划",
    "4": "日计划",
    "5": "临时计划",
}


@tool
def inspection_query_plan_detail(plan_id: str) -> dict[str, Any]:
    """查询巡检计划完整详情，供后续工单规划使用。"""

    normalized = plan_id.strip()
    if not normalized:
        return _error("missing_input", "计划 ID 不能为空")
    settings = get_inspection_settings()
    endpoint = settings.plan_detail_url
    if not endpoint:
        return _error("config_error", "未配置 INSPECTION_PLAN_DETAIL_URL")
    try:
        headers = get_inspection_auth_client().headers_sync()
    except InspectionAuthError as exc:
        return _error("config_error", f"获取 inspection AllCore token 失败，无法查询计划详情：{exc}")
    try:
        import httpx

        response = httpx.post(
            endpoint,
            json={"id": normalized},
            headers=headers,
            timeout=settings.api_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        return _error("upstream_error", f"巡检计划详情查询失败：{exc}")
    plan = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(plan, dict):
        return _error("invalid_upstream_response", "巡检计划详情响应无效")
    return {"ok": True, "planId": normalized, "plan": plan}


@tool
def inspection_query_coverage(
    line_name: str,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """查询线路杆塔的机场覆盖，并返回 covered/uncovered 两组。"""

    line = line_name.strip()
    if not line:
        return _error("missing_input", "线路名称不能为空")
    settings = get_settings()
    inspection_settings = get_inspection_settings()
    result = TextToSqlClient(
        settings.text_to_sql_base_url,
        settings.text_to_sql_timeout_seconds,
    ).query(
        datasource=inspection_settings.text_to_sql_datasource,
        question=f"查询线路名称为'{line}'的杆塔、航迹和机场覆盖情况",
    )
    if result.get("status") != "success":
        return result
    raw = result.get("data")
    rows = raw.get("rows", []) if isinstance(raw, dict) else []
    if not isinstance(rows, list):
        rows = []
    covered = [row for row in rows if isinstance(row, dict) and _has_coverage(row)]
    uncovered = [row for row in rows if isinstance(row, dict) and not _has_coverage(row)]
    return {
        "ok": True,
        "lineName": line,
        "rows": rows,
        "coveredRows": covered,
        "uncoveredRows": uncovered,
        "coveredCount": len(covered),
        "uncoveredCount": len(uncovered),
    }


@tool
def inspection_build_work_order_fill_state(
    plan: dict[str, Any],
    coverage_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """根据计划和覆盖结果生成旧前端可直接消费的工单填充状态。"""

    rows = coverage_rows or []
    details = [_row_to_detail(row) for row in rows]
    details = [detail for detail in details if detail is not None]
    method = "dock" if any(_has_coverage(row) for row in rows) else "drone"
    payload = {
        "planGuid": plan.get("planGuid") or plan.get("plan_guid"),
        "priority": 3,
        "major": plan.get("major") or "tms",
        "workNature": plan.get("workNature") or "fine_inspect_tms",
        "isCycle": "0" if str(plan.get("planType")) == "5" else "1",
        "inspectionMethod": method,
        "equipSn": None,
        "photoStorageType": "visible,ir",
        "panoShot": False,
        "isRecord": 1,
        "flightWorkers": None,
        "workContent": f"基于巡检计划自动生成工单：{plan.get('planName') or ''}"[:100],
        "startDate": plan.get("inspectStartTime") or plan.get("inspect_start_time"),
        "endDate": plan.get("inspectEndTime") or plan.get("inspect_end_time"),
        "isTerrain": False,
        "orderDetailList": details,
    }
    group = "covered" if method == "dock" else "uncovered"
    state = {
        "intentCode": "createTempOrder",
        "actionCode": "createTempOrder",
        "actionName": "创建工单",
        "executeApi": "/order/createTempOrder",
        "executeMethod": "POST",
        "routePath": "/workOrder/review",
        "filledFields": payload,
        "displayFields": {
            "planName": plan.get("planName"),
            "planTypeName": PLAN_TYPES.get(str(plan.get("planType")), plan.get("planTypeZh")),
            "lineName": plan.get("lineName"),
            "orderDetailCount": len(details),
        },
        "missingFields": [],
        "ambiguousFields": [],
        "invalidFields": [],
        "executePayload": payload if details else None,
        "status": "READY" if details else "NEED_MORE_INFO",
        "nextQuestion": None if details else "未查询到可创建工单的杆塔数据。",
        "pendingWorkOrderGroups": [group] if details else [],
    }
    return {"ok": bool(details), "workOrderFillState": state}


def _has_coverage(row: dict[str, Any]) -> bool:
    for key in ("dockGuid", "dockName", "airportGuid", "airportName", "airport_uid", "airport_name", "机场uid", "机场名称"):
        if row.get(key):
            return True
    value = row.get("covered", row.get("isCovered", row.get("是否覆盖")))
    return value is True or str(value) in {"1", "true", "True", "是", "已覆盖", "covered"}


def _row_to_detail(row: dict[str, Any]) -> dict[str, Any] | None:
    device_guid = row.get("deviceGuid") or row.get("tower_uid") or row.get("towerGuid") or row.get("杆塔uid")
    parent_guid = row.get("parentDeviceGuid") or row.get("line_uid") or row.get("lineGuid") or row.get("线路uid")
    if not device_guid or not parent_guid:
        return None
    return {
        "trackVersion": row.get("trackVersion") or row.get("track_version") or "",
        "dockGuid": row.get("dockGuid") or row.get("airportGuid") or row.get("airport_uid") or "",
        "fileGuid": row.get("fileGuid") or row.get("file_guid") or "",
        "latitude": row.get("latitude") or row.get("lat") or "",
        "routeGuid": row.get("routeGuid") or row.get("route_guid") or parent_guid,
        "deviceName": row.get("deviceName") or row.get("tower_name") or row.get("towerName") or row.get("杆塔名称"),
        "workNature": row.get("workNature") or row.get("work_nature") or "fine_inspect_tms",
        "isMainTower": row.get("isMainTower", True),
        "parentDeviceGuid": parent_guid,
        "major": row.get("major") or row.get("专业") or "tms",
        "deviceGuid": device_guid,
        "parentDeviceName": row.get("parentDeviceName") or row.get("line_name") or row.get("lineName") or row.get("线路名称"),
        "dockName": row.get("dockName") or row.get("airportName") or row.get("airport_name") or "",
        "longitude": row.get("longitude") or row.get("lng") or "",
    }


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "errorCode": code, "error": message, "retryable": code == "upstream_error"}
