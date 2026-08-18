"""Inspection-specific read and planning workflows migrated from the legacy service."""

from __future__ import annotations

import re
from typing import Annotated, Any

from langchain_core.tools import InjectedToolArg, tool
from pydantic import BaseModel, field_validator, ValidationError

from app.integrations.inspection.models import (
    CreateInspectionPlanInput,
    PLAN_TYPES,
    normalize_plan_object,
)
from app.adapters.text_to_sql import TextToSqlClient
from app.core.config import get_settings
from app.core.runtime_context import get_runtime_context
from app.integrations.inspection.allcore_auth import (
    InspectionAllCoreAuthError,
    get_inspection_allcore_auth_client,
)
from app.integrations.inspection.config import get_inspection_settings
from app.integrations.inspection.coverage import (
    has_coverage as _has_coverage,
    haversine as _haversine,
    map_route as _map_route,
    merge_tower_coverage as _merge_tower_coverage,
    nearest_airport as _nearest_airport,
    query_plan_coverage_rows as _query_plan_coverage_rows,
)
from app.integrations.inspection.workflow_shared import (
    as_float as _as_float,
    coerce_list_argument as _coerce_list_argument,
    coerce_mapping_argument as _coerce_mapping_argument,
    coerce_string_list_argument as _coerce_string_list_argument,
    complete_plan_object as _complete_plan_object,
    error as _error,
    find_rows as _find_rows,
    first_present as _first_present,
    first_row_value as _first_row_value,
    rows_from_text2sql_result as _rows_from_text2sql_result,
    tower_range_invalid_message as _tower_range_invalid_message,
)
from app.integrations.inspection.work_order_summary import (
    display_work_order_method as _display_work_order_method,
    display_work_order_time as _display_work_order_time,
    display_work_order_value as _display_work_order_value,
    merge_created_work_orders as _merge_created_work_orders,
    work_order_aliases as _work_order_aliases,
    work_order_final_summary as _work_order_final_summary,
)
from app.tools.datetime_tool import resolve_datetime_expression


_CURRENT_PLAN_OBJECTS_KEY = "_inspection_current_plan_objects"


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
    client = TextToSqlClient(
        settings.text_to_sql_base_url,
        settings.text_to_sql_timeout_seconds,
    )
    result = client.query(
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

    runtime = get_runtime_context()
    if runtime.session_id:
        runtime.metadata[_CURRENT_PLAN_OBJECTS_KEY] = plan_object_list
    return {
        "ok": True,
        "lineName": parent_name,
        "ranges": normalized_ranges,
        "question": question,
        "planObjectListRef": "current_query_result",
        "count": len(plan_object_list),
        "planObjectListNames": [item["deviceName"] for item in plan_object_list],
        "skippedCount": len(skipped_rows),
        "summary": (
            f"已获取 {len(plan_object_list)} 条杆塔数据。完整 planObjectList 已保存在当前请求中，"
            "请直接调用 inspection_build_plan_fill_state 组装计划。"
        ),
    }


@tool
def inspection_build_plan_fill_state(
    plan_type: str,
    # 旧调用方仍可传入该参数，但不把大列表暴露给模型生成。
    plan_object_list: Annotated[
        list[dict[str, Any]] | str | None,
        InjectedToolArg,
    ] = None,
    time_expression: str | None = None,
    inspect_start_time: str | None = None,
    inspect_end_time: str | None = None,
    plan_object_ref: str | None = None,
) -> dict[str, Any]:
    """按规则组装计划；自然语言时间存在时以确定性解析结果为准。"""

    cached_plan_objects = get_runtime_context().metadata.get(_CURRENT_PLAN_OBJECTS_KEY)
    if isinstance(cached_plan_objects, list) and (
        plan_object_ref in (None, "", "current_query_result")
        or isinstance(plan_object_list, str)
    ):
        plan_object_list = cached_plan_objects
    elif plan_object_list is not None:
        try:
            plan_object_list = _coerce_list_argument(plan_object_list, "plan_object_list")
        except (TypeError, ValueError) as exc:
            return _error("invalid_plan_objects", str(exc))
    if not isinstance(plan_object_list, list) or not plan_object_list:
        return _error(
            "missing_plan_objects",
            "缺少已查询的真实 planObjectList，请先调用 inspection_query_device_data。",
        )

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
        "_framework": {
            "direct_action": {
                "action_id": "inspection.create_plan",
                "params": payload,
            }
        },
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
    client = TextToSqlClient(
        settings.text_to_sql_base_url,
        settings.text_to_sql_timeout_seconds,
    )
    result = client.query(
        datasource=inspection_settings.text_to_sql_datasource,
        question=(
            f"查询工单 id={normalized} 的工单编号、工单内容、工单状态、巡检方式、"
            "专业、开始时间、结束时间、作业对象数量、关联计划guid、计划名称、"
            "计划类型、计划巡检开始时间和计划巡检结束时间"
        ),
    )
    if result.get("status") != "success":
        return result
    rows = _rows_from_text2sql_result(result)
    if not rows:
        return _error("work_order_not_found", f"未查询到工单 ID {normalized} 的入库记录")
    work_order = rows[0]
    plan_guid = _first_present(work_order, "plan_guid", "planGuid")
    inspection_method = str(
        _first_present(work_order, "inspection_method", "inspectionMethod") or ""
    ).lower()
    completed_group = (
        "covered"
        if inspection_method == "dock"
        else "uncovered"
        if inspection_method == "drone"
        else None
    )
    if not plan_guid:
        return _error(
            "work_order_plan_missing",
            f"工单 ID {normalized} 已入库，但未查询到关联计划 GUID",
        )
    created_result = client.query(
        datasource=inspection_settings.text_to_sql_datasource,
        question=(
            f"查询计划 plan_guid={plan_guid} 下已创建成功的所有巡检工单的"
            "工单ID、工单编号、工单内容、巡检方式、开始时间和结束时间"
        ),
    )
    if created_result.get("status") != "success":
        return created_result
    created_work_orders = _merge_created_work_orders(
        _rows_from_text2sql_result(created_result),
        {**work_order, "id": _first_present(work_order, "id", "workOrderId") or normalized},
    )
    completed_methods = {
        str(_first_present(item, "inspection_method", "inspectionMethod") or "").lower()
        for item in [work_order, *created_work_orders]
    }
    completed_groups = [
        group
        for group, method in (("covered", "dock"), ("uncovered", "drone"))
        if method in completed_methods
    ]
    return {
        "ok": True,
        "workOrderId": normalized,
        "workOrder": work_order,
        "planGuid": plan_guid,
        "completedGroup": completed_group,
        "completedGroups": completed_groups,
        "createdWorkOrders": created_work_orders,
        "plan": {
            "planGuid": plan_guid,
            "planName": _first_present(work_order, "plan_name", "planName"),
            "planType": _first_present(work_order, "plan_type", "planType"),
            "inspectStartTime": _first_present(
                work_order,
                "inspect_start_time",
                "inspectStartTime",
                "plan_inspect_start_time",
            ),
            "inspectEndTime": _first_present(
                work_order,
                "inspect_end_time",
                "inspectEndTime",
                "plan_inspect_end_time",
            ),
        },
        "summary": f"工单 ID {normalized} 已完成入库校验。",
    }


class InspectionWorkOrderFillArgs(BaseModel):
    plan: dict[str, Any]
    coverage_rows: list[dict[str, Any]] | None = None
    group: str | None = None
    completed_groups: list[str] | None = None
    created_work_orders: list[dict[str, Any]] | None = None
    equip_sn: str | None = None
    flight_workers: list[str] | None = None

    @field_validator("plan", mode="before")
    @classmethod
    def decode_plan(cls, value: Any) -> dict[str, Any]:
        return _coerce_mapping_argument(value, "plan")

    @field_validator("coverage_rows", "created_work_orders", mode="before")
    @classmethod
    def decode_object_lists(cls, value: Any, info: Any) -> list[dict[str, Any]]:
        return _coerce_list_argument(value, info.field_name)

    @field_validator("completed_groups", "flight_workers", mode="before")
    @classmethod
    def decode_string_lists(cls, value: Any, info: Any) -> list[str]:
        return _coerce_string_list_argument(value, info.field_name)


@tool(args_schema=InspectionWorkOrderFillArgs)
def inspection_build_work_order_fill_state(
    plan: dict[str, Any],
    coverage_rows: list[dict[str, Any]] | None = None,
    group: str | None = None,
    completed_groups: list[str] | None = None,
    created_work_orders: list[dict[str, Any]] | None = None,
    equip_sn: str | None = None,
    flight_workers: list[str] | None = None,
) -> dict[str, Any]:
    """按机场覆盖拆分工单，每次仅组装待创建队列中的一个工单。"""

    try:
        normalized_plan = _coerce_mapping_argument(plan, "plan")
        rows = _coerce_list_argument(coverage_rows, "coverage_rows")
        normalized_completed_groups = _coerce_string_list_argument(
            completed_groups,
            "completed_groups",
        )
        normalized_created_work_orders = _coerce_list_argument(
            created_work_orders,
            "created_work_orders",
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
        tower_count = len({
            str(row.get("deviceGuid") or row.get("tower_guid") or row.get("tower_uid"))
            for row in rows
            if row.get("deviceGuid") or row.get("tower_guid") or row.get("tower_uid")
        })
        work_order_count = len(normalized_created_work_orders) or len(normalized_completed_groups)
        plan_name = normalized_plan.get("planName") or normalized_plan.get("plan_name") or "-"
        return {
            "ok": True,
            "workOrderFillState": {
                "status": "COMPLETED",
                "pendingWorkOrderGroups": [],
                "executePayload": None,
            },
            "summary": "该计划的巡检工单已全部创建完成。",
            "finalSummary": _work_order_final_summary(
                normalized_created_work_orders,
                plan_name=plan_name,
            ),
            "workOrderCount": work_order_count,
            "towerCount": tower_count,
            "planName": plan_name,
            "createdWorkOrders": normalized_created_work_orders,
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
