"""Inspection-specific read and planning workflows migrated from the legacy service."""

from __future__ import annotations

import re
from typing import Any

from langchain_core.tools import tool
from pydantic import ValidationError

from app.integrations.inspection.models import (
    CreateInspectionPlanInput,
    PLAN_TYPES,
    normalize_plan_object,
)
from app.adapters.text_to_sql import TextToSqlClient
from app.core.config import get_settings
from app.integrations.inspection.auth import InspectionAuthError, get_inspection_auth_client
from app.integrations.inspection.config import get_inspection_settings
from app.tools.datetime_tool import resolve_datetime_expression


@tool
def inspection_query_device_data(parent_device_name: str, ranges: str = "全部") -> dict[str, Any]:
    """按逻辑查询线路杆塔，并确定性组装 create_plan 所需的 planObjectList。

    创建巡检计划前必须先调用本工具，禁止由模型自行编造 deviceGuid/parentDeviceGuid。
    """

    parent_name = parent_device_name.strip()
    normalized_ranges = ranges.strip() or "全部"
    if not parent_name:
        return _error("missing_input", "线路名称不能为空")

    settings = get_settings()
    inspection_settings = get_inspection_settings()
    question = f"查询{parent_name}线路下{normalized_ranges}的杆塔uid、杆塔名称、杆塔专业、线路uid、线路名称"
    result = TextToSqlClient(
        settings.text_to_sql_base_url,
        settings.text_to_sql_timeout_seconds,
    ).query(
        datasource=inspection_settings.text_to_sql_datasource,
        question=question,
    )
    if result.get("status") != "success":
        return result

    rows = _rows_from_text2sql_result(result)
    invalid_range_message = _tower_range_invalid_message(parent_name, normalized_ranges, rows)
    if invalid_range_message is not None:
        return {
            "ok": False,
            "errorCode": "invalid_tower_range",
            "error": invalid_range_message,
            "retryable": False,
            "question": question,
            "rows": rows,
            "planObjectList": [],
        }

    plan_object_list = []
    skipped_rows = []
    for row in rows:
        plan_object = normalize_plan_object(row)
        if not _complete_plan_object(plan_object):
            skipped_rows.append(row)
            continue
        plan_object_list.append(plan_object)

    if not plan_object_list:
        return {
            "ok": False,
            "errorCode": "empty_plan_objects",
            "error": "未查询到可用于创建计划的真实杆塔数据，请核实线路名称或杆塔范围。",
            "retryable": False,
            "question": question,
            "rows": rows,
            "planObjectList": [],
            "skippedRows": skipped_rows,
        }

    return {
        "ok": True,
        "lineName": parent_name,
        "ranges": normalized_ranges,
        "question": question,
        "rows": rows,
        "planObjectList": plan_object_list,
        "count": len(plan_object_list),
        "skippedRows": skipped_rows,
        "summary": f"已获取 {len(plan_object_list)} 条杆塔数据，创建计划时请直接使用 planObjectList。",
    }


@tool
def inspection_build_plan_fill_state(
    plan_type: str,
    plan_object_list: list[dict[str, Any]],
    time_expression: str | None = None,
    inspect_start_time: str | None = None,
    inspect_end_time: str | None = None,
) -> dict[str, Any]:
    """按规则组装计划；自然语言时间存在时以确定性解析结果为准。"""

    if isinstance(time_expression, str) and time_expression.strip():
        try:
            resolved = resolve_datetime_expression(
                time_expression,
                get_inspection_settings().timezone,
                compare_to_today=True,
            )
        except ValueError as exc:
            return _error("invalid_datetime_expression", str(exc))
        if resolved["is_before_today"]:
            return _error(
                "expired_inspection_date",
                f"巡检日期 {resolved['date']} 已早于今天 {resolved['today']}，请提供新的巡检日期。",
            )
        span = resolved.get("time_span")
        if isinstance(span, dict):
            inspect_start_time = str(span["start_datetime"])
            inspect_end_time = str(span["end_datetime"])
        else:
            inspect_start_time = f"{resolved['date']} 00:00:00"
            inspect_end_time = f"{resolved['date']} 23:59:59"
    else:
        if not inspect_start_time or not inspect_end_time:
            return _error("missing_input", "缺少巡检时间")
        try:
            resolved = resolve_datetime_expression(
                inspect_start_time,
                get_inspection_settings().timezone,
                compare_to_today=True,
            )
        except ValueError as exc:
            return _error("invalid_datetime_expression", str(exc))
        if resolved["is_before_today"]:
            return _error(
                "expired_inspection_date",
                f"巡检日期 {resolved['date']} 已早于今天 {resolved['today']}，请提供新的巡检日期。",
            )

    try:
        plan = CreateInspectionPlanInput.model_validate({
            "planType": plan_type,
            "planName": "由巡检插件生成",
            "inspectStartTime": inspect_start_time,
            "inspectEndTime": inspect_end_time,
            "planObjectList": plan_object_list,
        })
    except ValidationError as exc:
        return _error("invalid_plan_fields", str(exc))
    payload = plan.model_dump(mode="json", by_alias=True)
    return {
        "ok": True,
        "executePayload": payload,
        "displayFields": {
            "planName": payload["planName"],
            "planType": PLAN_TYPES[payload["planType"]],
            "inspectStartTime": payload["inspectStartTime"],
            "inspectEndTime": payload["inspectEndTime"],
            "planObjectListNames": [
                item["deviceName"] for item in payload["planObjectList"]
            ],
        },
        "summary": "已按规则生成计划类型、计划名称和巡检对象。",
    }


@tool
def inspection_query_plan_detail(plan_id: str) -> dict[str, Any]:
    """查询巡检计划完整详情；仅在用户明确触发工单流程或查询计划详情时使用。"""

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
    """查询线路杆塔的机场覆盖；仅在用户明确触发工单规划时用于分组。"""

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
    """根据计划和覆盖结果生成旧前端可消费的工单填充状态；仅在用户明确创建工单时使用。"""

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


def _rows_from_text2sql_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    data = result.get("data")
    rows = _find_rows(data)
    return [row for row in rows if isinstance(row, dict)]


def _complete_plan_object(item: dict[str, Any]) -> bool:
    return all(
        not (item.get(key) is None or (isinstance(item.get(key), str) and item.get(key).strip() == ""))
        for key in ("deviceGuid", "deviceName", "major", "parentDeviceGuid", "parentDeviceName")
    )


def _find_rows(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    rows = value.get("rows")
    if isinstance(rows, list):
        return rows
    data = value.get("data")
    if data is not value:
        nested = _find_rows(data)
        if nested:
            return nested
    result = value.get("result")
    if result is not value:
        nested = _find_rows(result)
        if nested:
            return nested
    return []


def _requested_tower_count(ranges: str) -> int | None:
    text = (ranges or "").strip()
    if not text or text in {"全部", "所有", "ALL", "all"}:
        return None

    range_match = re.search(r"(\d+)\s*(?:-|~|到|至)\s*(\d+)", text)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start > end:
            start, end = end, start
        return end - start + 1

    numbers = [int(value) for value in re.findall(r"\d+", text)]
    if not numbers:
        return None
    return len(set(numbers))


def _tower_range_invalid_message(
    parent_device_name: str,
    ranges: str,
    rows: list[dict[str, Any]],
) -> str | None:
    requested_count = _requested_tower_count(ranges)
    if requested_count is None or requested_count <= len(rows):
        return None

    suggestion = f"是否需要帮您指定巡检1-{len(rows)}号杆塔，" if rows else ""
    return (
        f"{parent_device_name} 线路下仅查询到 {len(rows)} 基符合条件的杆塔，"
        f"少于您输入的范围“{ranges}”对应的 {requested_count} 基杆塔。"
        f"{suggestion}或者请您重新输入需要巡检的有效杆塔范围。"
    )


def _error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "errorCode": code, "error": message, "retryable": code == "upstream_error"}
