"""Inspection-specific read and planning workflows migrated from the legacy service."""

from __future__ import annotations

import json
import math
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
from app.integrations.inspection.allcore_auth import (
    InspectionAllCoreAuthError,
    get_inspection_allcore_auth_client,
)
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
    auth_client = get_inspection_allcore_auth_client()
    try:
        import httpx

        response = auth_client.request_with_retry_sync(
            lambda headers: httpx.post(
                endpoint,
                json={"id": normalized},
                headers=headers,
                timeout=settings.api_timeout_seconds,
            )
        )
        response.raise_for_status()
        payload = response.json()
    except InspectionAllCoreAuthError as exc:
        error_code = "auth_error" if auth_client.is_configured() else "config_error"
        return _error(error_code, str(exc))
    except (httpx.HTTPError, ValueError) as exc:
        return _error("upstream_error", f"巡检计划详情查询失败：{exc}")
    plan = payload.get("data") if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or str(payload.get("code")) != "200"
        or not isinstance(plan, dict)
    ):
        return _error("invalid_upstream_response", "巡检计划详情响应无效")
    return {"ok": True, "planId": normalized, "plan": plan}


@tool
def inspection_query_coverage(
    line_name: str | None = None,
    plan_guid: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """查询线路杆塔的机场覆盖；仅在用户明确触发工单规划时用于分组。"""

    del filters
    line = (line_name or "").strip()
    guid = (plan_guid or "").strip()
    if not line and not guid:
        return _error("missing_input", "线路名称和计划 GUID 至少提供一个")
    settings = get_settings()
    inspection_settings = get_inspection_settings()
    client = TextToSqlClient(
        settings.text_to_sql_base_url,
        settings.text_to_sql_timeout_seconds,
    )
    if guid:
        result = _query_plan_coverage_rows(
            client,
            inspection_settings.text_to_sql_datasource,
            guid,
        )
    else:
        result = client.query(
            datasource=inspection_settings.text_to_sql_datasource,
            question=f"查询线路名称为'{line}'的杆塔、航迹和机场覆盖情况",
        )
    if result.get("status") != "success":
        return result
    rows = _rows_from_text2sql_result(result)
    covered = [row for row in rows if isinstance(row, dict) and _has_coverage(row)]
    uncovered = [row for row in rows if isinstance(row, dict) and not _has_coverage(row)]
    return {
        "ok": True,
        "lineName": line,
        "planGuid": guid,
        "rows": rows,
        "coveredRows": covered,
        "uncoveredRows": uncovered,
        "coveredCount": len(covered),
        "uncoveredCount": len(uncovered),
    }


def _query_plan_coverage_rows(
    client: TextToSqlClient,
    datasource: str,
    plan_guid: str,
) -> dict[str, Any]:
    tower_result = client.query(
        datasource=datasource,
        question=(
            f"查询计划 plan_guid={plan_guid} 下所有杆塔的杆塔guid、杆塔名称、线路guid、线路名称、"
            "专业、作业性质、经度、纬度、海拔、电压等级、电压等级中文、杆塔性质和杆塔排序号"
        ),
    )
    if tower_result.get("status") != "success":
        return tower_result
    towers = _rows_from_text2sql_result(tower_result)
    if not towers:
        return _error("empty_plan_towers", f"计划 {plan_guid} 下未查询到杆塔数据")

    device_guids = [
        str(_first_present(row, "device_guid", "deviceGuid", "tower_guid", "tower_uid"))
        for row in towers
        if _first_present(row, "device_guid", "deviceGuid", "tower_guid", "tower_uid")
    ]
    route_result = client.query(
        datasource=datasource,
        question=(
            f"查询杆塔 device_guid 在 [{ '、'.join(device_guids) }] 中的所有航迹信息，"
            "包含航迹guid、杆塔guid、线路guid、航迹文件、航迹版本和航迹内容"
        ),
    )
    if route_result.get("status") != "success":
        return route_result
    airport_result = client.query(
        datasource=datasource,
        question="查询所有机场/机巢的机场guid、机场名称、经度、纬度和巡检半径",
    )
    if airport_result.get("status") != "success":
        return airport_result

    routes_by_device: dict[str, list[dict[str, Any]]] = {}
    for row in _rows_from_text2sql_result(route_result):
        device_guid = _first_present(row, "device_guid", "deviceGuid", "tower_guid", "tower_uid")
        if device_guid:
            routes_by_device.setdefault(str(device_guid), []).append(_map_route(row))
    airports = _rows_from_text2sql_result(airport_result)
    rows = [
        _merge_tower_coverage(row, routes_by_device, airports, index)
        for index, row in enumerate(towers, start=1)
    ]
    return {"status": "success", "data": {"rows": rows}}


def _merge_tower_coverage(
    tower: dict[str, Any],
    routes_by_device: dict[str, list[dict[str, Any]]],
    airports: list[dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    device_guid = _first_present(tower, "device_guid", "deviceGuid", "tower_guid", "tower_uid")
    parent_device_guid = _first_present(
        tower,
        "parent_device_guid",
        "parentDeviceGuid",
        "line_guid",
        "line_uid",
    )
    longitude = _as_float(_first_present(tower, "longitude", "lng"))
    latitude = _as_float(_first_present(tower, "latitude", "lat"))
    airport = _nearest_airport(longitude, latitude, airports)
    routes = [
        {
            **route,
            "parentDeviceGuid": route.get("parentDeviceGuid") or parent_device_guid,
        }
        for route in routes_by_device.get(str(device_guid), [])
    ]
    first_route = routes[0] if routes else {}
    route_fields = {
        key: value
        for key, value in first_route.items()
        if key not in {"deviceGuid", "parentDeviceGuid"}
    }
    return {
        **tower,
        "deviceGuid": device_guid,
        "deviceName": _first_present(tower, "device_name", "deviceName", "basic_tower_ledger_name", "tower_name"),
        "parentDeviceGuid": parent_device_guid,
        "parentDeviceName": _first_present(tower, "parent_device_name", "parentDeviceName", "basic_line_ledger_name", "line_name"),
        "major": _first_present(tower, "major", "专业") or "tms",
        "workNature": _first_present(tower, "work_nature", "workNature"),
        "towerSort": _first_present(tower, "tower_sort", "towerSort") or index,
        "longitude": longitude,
        "latitude": latitude,
        "dockGuid": _first_present(airport or {}, "dock_guid", "dockGuid", "airport_guid", "airportGuid"),
        "dockName": _first_present(airport or {}, "dock_name", "dockName", "airport_name", "airportName"),
        "deviceRouteList": routes,
        **route_fields,
    }


def _map_route(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "routeGuid": _first_present(row, "route_guid", "routeGuid"),
        "parentDeviceGuid": _first_present(row, "parent_device_guid", "parentDeviceGuid"),
        "deviceGuid": _first_present(row, "device_guid", "deviceGuid"),
        "routeDescription": _first_present(row, "route_description", "routeDescription"),
        "fileGuid": _first_present(row, "file_guid", "fileGuid"),
        "fileType": _first_present(row, "file_type", "fileType"),
        "trackVersion": _first_present(row, "track_version", "trackVersion"),
        "routeContent": _first_present(row, "route_content", "routeContent"),
    }


def _nearest_airport(
    longitude: float | None,
    latitude: float | None,
    airports: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if longitude is None or latitude is None:
        return None
    nearest: dict[str, Any] | None = None
    nearest_distance = float("inf")
    for airport in airports:
        airport_longitude = _as_float(_first_present(airport, "longitude", "lng"))
        airport_latitude = _as_float(_first_present(airport, "latitude", "lat"))
        if airport_longitude is None or airport_latitude is None:
            continue
        radius = _as_float(_first_present(airport, "inspection_radius", "inspectionRadius")) or 3000.0
        distance = _haversine(longitude, latitude, airport_longitude, airport_latitude)
        if distance <= radius and distance < nearest_distance:
            nearest = airport
            nearest_distance = distance
    return nearest


def _haversine(longitude1: float, latitude1: float, longitude2: float, latitude2: float) -> float:
    radius = 6_371_000.0
    latitude1_radians = math.radians(latitude1)
    latitude2_radians = math.radians(latitude2)
    latitude_delta = math.radians(latitude2 - latitude1)
    longitude_delta = math.radians(longitude2 - longitude1)
    value = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(latitude1_radians)
        * math.cos(latitude2_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def _as_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


@tool
def inspection_query_work_order_resources() -> dict[str, Any]:
    """查询人工飞手巡检所需的可用无人机与飞手。"""

    settings = get_inspection_settings()
    base = (settings.api_base_url or "").rstrip("/")
    drone_url = settings.drone_list_url or (
        f"{base}/api/main-server/equip/drone/list" if base else None
    )
    worker_url = settings.flight_worker_list_url or (
        f"{base}/api/main-server/person/fieldWorkInfo/getList" if base else None
    )
    if not drone_url or not worker_url:
        return _error(
            "config_error",
            "未配置巡检无人机或飞手查询地址",
        )
    auth_client = get_inspection_allcore_auth_client()
    try:
        import httpx

        drone_response = auth_client.request_with_retry_sync(
            lambda headers: httpx.get(
                drone_url,
                headers=headers,
                timeout=settings.api_timeout_seconds,
            )
        )
        drone_response.raise_for_status()
        worker_response = auth_client.request_with_retry_sync(
            lambda headers: httpx.post(
                worker_url,
                json={"deviceType": ""},
                headers=headers,
                timeout=settings.api_timeout_seconds,
            )
        )
        worker_response.raise_for_status()
        drones = [item for item in _find_rows(drone_response.json()) if isinstance(item, dict)]
        workers = [item for item in _find_rows(worker_response.json()) if isinstance(item, dict)]
    except InspectionAllCoreAuthError as exc:
        error_code = "auth_error" if auth_client.is_configured() else "config_error"
        return _error(error_code, str(exc))
    except (httpx.HTTPError, ValueError) as exc:
        return _error("upstream_error", f"巡检资源查询失败：{exc}")

    equip_sn = _first_row_value(drones, "equipSn", "sn", "deviceSn", "deviceCode")
    worker_id = _first_row_value(workers, "id", "userId", "personId", "workerId")
    return {
        "ok": True,
        "drones": drones,
        "flightWorkers": workers,
        "suggestedEquipSn": equip_sn,
        "suggestedFlightWorkers": [str(worker_id)] if worker_id not in (None, "") else [],
    }


@tool
def inspection_query_work_order_detail(order_id: str) -> dict[str, Any]:
    """按业务系统返回的工单 ID 校验工单已真实入库。"""

    normalized = order_id.strip()
    if not normalized:
        return _error("missing_input", "工单 ID 不能为空")
    settings = get_settings()
    inspection_settings = get_inspection_settings()
    result = TextToSqlClient(
        settings.text_to_sql_base_url,
        settings.text_to_sql_timeout_seconds,
    ).query(
        datasource=inspection_settings.text_to_sql_datasource,
        question=(
            f"查询工单 id={normalized} 的工单编号、工单内容、工单状态、巡检方式、"
            "专业、开始时间、结束时间和作业对象数量"
        ),
    )
    if result.get("status") != "success":
        return result
    rows = _rows_from_text2sql_result(result)
    if not rows:
        return _error("work_order_not_found", f"未查询到工单 ID {normalized} 的入库记录")
    return {
        "ok": True,
        "workOrderId": normalized,
        "workOrder": rows[0],
        "summary": f"工单 ID {normalized} 已完成入库校验。",
    }


@tool
def inspection_build_work_order_fill_state(
    plan: dict[str, Any] | str,
    coverage_rows: list[dict[str, Any]] | str | None = None,
    group: str | None = None,
    completed_groups: list[str] | str | None = None,
    equip_sn: str | None = None,
    flight_workers: list[str] | str | None = None,
) -> dict[str, Any]:
    """按机场覆盖拆分工单，每次仅组装待创建队列中的一个工单。"""

    try:
        normalized_plan = _coerce_mapping_argument(plan, "plan")
        rows = _coerce_list_argument(coverage_rows, "coverage_rows")
        normalized_completed_groups = _coerce_string_list_argument(
            completed_groups,
            "completed_groups",
        )
    except (TypeError, ValueError) as exc:
        return _error("invalid_arguments", str(exc))
    grouped_rows = {
        "covered": [row for row in rows if _has_coverage(row)],
        "uncovered": [row for row in rows if not _has_coverage(row)],
    }
    all_groups = [name for name in ("covered", "uncovered") if grouped_rows[name]]
    completed = {name for name in normalized_completed_groups if name in all_groups}
    pending_groups = [name for name in all_groups if name not in completed]
    selected_group = group if group in pending_groups else (pending_groups[0] if pending_groups else None)
    if selected_group is None:
        return {
            "ok": True,
            "workOrderFillState": {
                "status": "COMPLETED",
                "pendingWorkOrderGroups": [],
                "executePayload": None,
            },
            "summary": "该计划的巡检工单已全部创建完成。",
        }

    details = [_row_to_detail(row) for row in grouped_rows[selected_group]]
    details = [detail for detail in details if detail is not None]
    method = "dock" if selected_group == "covered" else "drone"
    major = str(normalized_plan.get("major") or (details[0].get("major") if details else None) or "tms")
    plan_type = str(normalized_plan.get("planType") or normalized_plan.get("plan_type") or "")
    plan_type_code = _plan_type_code(plan_type)
    missing_fields = []
    if not (normalized_plan.get("planGuid") or normalized_plan.get("plan_guid")):
        missing_fields.append("planGuid")
    if not (normalized_plan.get("inspectStartTime") or normalized_plan.get("inspect_start_time")):
        missing_fields.append("startDate")
    if not (normalized_plan.get("inspectEndTime") or normalized_plan.get("inspect_end_time")):
        missing_fields.append("endDate")
    if method == "drone" and not equip_sn:
        missing_fields.append("equipSn")
    if method == "drone" and not flight_workers:
        missing_fields.append("flightWorkers")
    payload = {
        "planGuid": normalized_plan.get("planGuid") or normalized_plan.get("plan_guid"),
        "priority": _work_order_priority(plan_type_code),
        "major": major,
        "workNature": normalized_plan.get("workNature") or normalized_plan.get("work_nature") or _work_nature(major),
        "isCycle": "0" if plan_type_code == "5" else "1",
        "inspectionMethod": method,
        "equipSn": equip_sn if method == "drone" else None,
        "photoStorageType": _photo_storage_type(major, details),
        "panoShot": False,
        "isRecord": "1",
        "flightWorkers": flight_workers if method == "drone" else None,
        "workContent": _work_content(normalized_plan, details, plan_type_code),
        "startDate": normalized_plan.get("inspectStartTime") or normalized_plan.get("inspect_start_time"),
        "endDate": normalized_plan.get("inspectEndTime") or normalized_plan.get("inspect_end_time"),
        "isTerrain": False,
        "orderDetailList": details,
    }
    ready = bool(details) and not missing_fields
    state = {
        "intentCode": "createTempOrder",
        "actionCode": "createTempOrder",
        "actionName": "创建工单",
        "executeApi": "/order/createTempOrder",
        "executeMethod": "POST",
        "routePath": "/workOrder/review",
        "filledFields": payload,
        "displayFields": {
            "planName": normalized_plan.get("planName"),
            "planTypeName": PLAN_TYPES.get(str(normalized_plan.get("planType")), normalized_plan.get("planTypeZh")),
            "lineName": normalized_plan.get("lineName"),
            "workOrderGroup": selected_group,
            "inspectionMethodName": "固定机场巡检" if method == "dock" else "人工飞手无人机巡检",
            "orderDetailCount": len(details),
        },
        "missingFields": missing_fields,
        "ambiguousFields": [],
        "invalidFields": [],
        "executePayload": payload if ready else None,
        "status": "READY" if ready else "NEED_MORE_INFO",
        "nextQuestion": (
            None
            if ready
            else "未查询到可创建工单的杆塔数据。"
            if not details
            else "工单必要字段尚未补齐，请先核对计划详情和巡检资源。"
        ),
        "currentWorkOrderGroup": selected_group,
        "pendingWorkOrderGroups": pending_groups,
        "remainingWorkOrderGroups": [name for name in pending_groups if name != selected_group],
    }
    return {"ok": ready, "workOrderFillState": state}


def _has_coverage(row: dict[str, Any]) -> bool:
    for key in ("dockGuid", "dockName", "airportGuid", "airportName", "airport_uid", "airport_name", "机场uid", "机场名称"):
        if row.get(key):
            return True
    value = row.get("covered", row.get("isCovered", row.get("是否覆盖")))
    return value is True or str(value) in {"1", "true", "True", "是", "已覆盖", "covered"}


def _row_to_detail(row: dict[str, Any]) -> dict[str, Any] | None:
    device_guid = row.get("deviceGuid") or row.get("tower_guid") or row.get("tower_uid") or row.get("towerGuid") or row.get("杆塔uid")
    parent_guid = row.get("parentDeviceGuid") or row.get("line_guid") or row.get("line_uid") or row.get("lineGuid") or row.get("线路uid")
    if not device_guid or not parent_guid:
        return None
    major = row.get("major") or row.get("专业") or "tms"
    return {
        "dockGuid": row.get("dockGuid") or row.get("airportGuid") or row.get("airport_uid"),
        "dockName": row.get("dockName") or row.get("airportName") or row.get("airport_name"),
        "dockList": row.get("dockList"),
        "parentDeviceGuid": parent_guid,
        "parentDeviceName": row.get("parentDeviceName") or row.get("basic_line_ledger_name") or row.get("line_name") or row.get("lineName") or row.get("线路名称"),
        "deviceType": row.get("deviceType") or major,
        "deviceGuid": device_guid,
        "deviceName": row.get("deviceName") or row.get("basic_tower_ledger_name") or row.get("tower_name") or row.get("towerName") or row.get("杆塔名称"),
        "poleNature": row.get("poleNature") or row.get("pole_nature"),
        "towerSort": row.get("towerSort") or row.get("tower_sort") or row.get("sort"),
        "routeGuid": row.get("routeGuid") or row.get("route_guid"),
        "routeContent": row.get("routeContent") or row.get("route_content"),
        "routeDescription": row.get("routeDescription") or row.get("route_description"),
        "fileGuid": row.get("fileGuid") or row.get("file_guid"),
        "fileType": row.get("fileType") or row.get("file_type"),
        "deviceRouteList": row.get("deviceRouteList") or row.get("device_route_list") or [],
        "longitude": row.get("longitude") or row.get("lng"),
        "latitude": row.get("latitude") or row.get("lat"),
        "altitude": row.get("altitude"),
        "voltageLevel": row.get("voltageLevel") or row.get("voltage_level"),
        "voltageLevelZh": row.get("voltageLevelZh") or row.get("voltage_level_zh"),
        "promptInformation": row.get("promptInformation"),
        "disabled": bool(row.get("disabled", False)),
        "sort": row.get("sort") or row.get("towerSort") or row.get("tower_sort"),
        "terrain": bool(row.get("terrain", False)),
        "lineGuid": row.get("lineGuid") or parent_guid,
        "workNature": row.get("workNature") or row.get("work_nature") or _work_nature(str(major)),
        "major": major,
    }


def _coerce_mapping_argument(value: dict[str, Any] | str, name: str) -> dict[str, Any]:
    parsed = _load_json_argument(value, name)
    if not isinstance(parsed, dict):
        raise TypeError(f"{name} 必须是对象")
    return parsed


def _coerce_list_argument(
    value: list[dict[str, Any]] | str | None,
    name: str,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    parsed = _load_json_argument(value, name)
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise TypeError(f"{name} 必须是对象数组")
    return parsed


def _coerce_string_list_argument(
    value: list[str] | str | None,
    name: str,
) -> list[str]:
    if value is None:
        return []
    parsed = _load_json_argument(value, name)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise TypeError(f"{name} 必须是字符串数组")
    return parsed


def _load_json_argument(value: Any, name: str) -> Any:
    if not isinstance(value, str):
        return value
    candidate = value.strip()
    last_error: json.JSONDecodeError | None = None
    for _ in range(3):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            try:
                candidate = json.loads(f'"{candidate}"')
            except json.JSONDecodeError:
                break
            continue
        if isinstance(parsed, str) and parsed.strip().startswith(("{", "[")):
            candidate = parsed.strip()
            continue
        return parsed
    raise ValueError(f"{name} 不是有效的 JSON 字符串") from last_error


def _plan_type_code(value: str) -> str:
    normalized = value.strip()
    if normalized in PLAN_TYPES:
        return normalized
    return next((code for code, name in PLAN_TYPES.items() if name == normalized), normalized)


def _work_order_priority(plan_type: str) -> int:
    return {"1": 4, "2": 3, "3": 3, "4": 2, "5": 1}.get(plan_type, 3)


def _work_nature(major: str) -> str:
    return {
        "tms": "fine_inspect_tms",
        "dms": "fine_inspect_dms",
        "sms": "fine_inspect_sms",
    }.get(major, "fine_inspect_tms")


def _photo_storage_type(major: str, details: list[dict[str, Any]]) -> str:
    if major != "tms":
        return "visable"
    for detail in details:
        value = detail.get("voltageLevel") or detail.get("voltageLevelZh")
        match = re.search(r"\d+", str(value or ""))
        if match and int(match.group()) >= 500:
            return "visable,ir"
    return "visable"


def _work_content(
    plan: dict[str, Any],
    details: list[dict[str, Any]],
    plan_type: str,
) -> str:
    start = str(plan.get("inspectStartTime") or plan.get("inspect_start_time") or "")
    lines = [str(item.get("parentDeviceName") or "").strip() for item in details]
    line_names = "、".join(dict.fromkeys(name for name in lines if name))
    type_name = PLAN_TYPES.get(plan_type, str(plan.get("planTypeZh") or plan_type))
    return f"{start} {line_names} {type_name}，共{len(details)}基杆塔"[:100]


def _first_row_value(rows: list[dict[str, Any]], *keys: str) -> Any:
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
    return None


def _first_present(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        candidate = value.get(key)
        if candidate not in (None, ""):
            return candidate
    return None


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
    for key in ("rows", "records", "list"):
        rows = value.get(key)
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
