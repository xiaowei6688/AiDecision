"""Inspection-specific tower, route, and airport coverage projection."""

from __future__ import annotations

import math
from typing import Any, Protocol

from app.integrations.inspection.workflow_shared import (
    as_float,
    error,
    first_present,
    rows_from_text2sql_result,
)


class QueryClient(Protocol):
    def query(self, *, datasource: str, question: str) -> dict[str, Any]: ...


def query_plan_coverage_rows(
    client: QueryClient,
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
    towers = rows_from_text2sql_result(tower_result)
    if not towers:
        return error("empty_plan_towers", f"计划 {plan_guid} 下未查询到杆塔数据")

    device_guids = [
        str(first_present(row, "device_guid", "deviceGuid", "tower_guid", "tower_uid"))
        for row in towers
        if first_present(row, "device_guid", "deviceGuid", "tower_guid", "tower_uid")
    ]
    route_result = client.query(
        datasource=datasource,
        question=(
            f"查询杆塔 device_guid 在 [{ '、'.join(device_guids) }] 中的所有航迹信息，"
            "包含 id、route_guid、parent_device_guid、device_guid、device_type、route_description、"
            "file_guid、file_type、route_type、route_version_type、route_source、"
            "adapted_model、track_version、track_type、route_content、"
            "description、upload_source、dept_code、create_user、create_time、"
            "update_user、update_time、is_deleted、create_dept"
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
    for row in rows_from_text2sql_result(route_result):
        device_guid = first_present(row, "device_guid", "deviceGuid", "tower_guid", "tower_uid")
        if device_guid:
            routes_by_device.setdefault(str(device_guid), []).append(map_route(row))
    airports = rows_from_text2sql_result(airport_result)
    rows = [
        merge_tower_coverage(row, routes_by_device, airports, index)
        for index, row in enumerate(towers, start=1)
    ]
    return {"status": "success", "data": {"rows": rows}}


def merge_tower_coverage(
    tower: dict[str, Any],
    routes_by_device: dict[str, list[dict[str, Any]]],
    airports: list[dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    device_guid = first_present(tower, "device_guid", "deviceGuid", "tower_guid", "tower_uid")
    parent_device_guid = first_present(
        tower,
        "parent_device_guid",
        "parentDeviceGuid",
        "line_guid",
        "line_uid",
    )
    longitude = as_float(first_present(tower, "longitude", "lng"))
    latitude = as_float(first_present(tower, "latitude", "lat"))
    airport = nearest_airport(longitude, latitude, airports)
    routes = [
        {**route, "parentDeviceGuid": route.get("parentDeviceGuid") or parent_device_guid}
        for route in routes_by_device.get(str(device_guid), [])
    ]
    first_route = routes[0] if routes else {}
    route_fields = {
        key: first_route.get(key)
        for key in ("routeGuid", "routeContent", "routeDescription", "fileGuid", "fileType")
    }
    return {
        **tower,
        "deviceGuid": device_guid,
        "deviceName": first_present(
            tower, "device_name", "deviceName", "basic_tower_ledger_name", "tower_name"
        ),
        "parentDeviceGuid": parent_device_guid,
        "parentDeviceName": first_present(
            tower, "parent_device_name", "parentDeviceName", "basic_line_ledger_name", "line_name"
        ),
        "major": first_present(tower, "major", "专业") or "tms",
        "workNature": first_present(tower, "work_nature", "workNature"),
        "towerSort": first_present(tower, "tower_sort", "towerSort") or index,
        "longitude": longitude,
        "latitude": latitude,
        "dockGuid": first_present(
            airport or {}, "dock_guid", "dockGuid", "airport_guid", "airportGuid"
        ),
        "dockName": first_present(
            airport or {}, "dock_name", "dockName", "airport_name", "airportName"
        ),
        "deviceRouteList": routes,
        **route_fields,
    }


def map_route(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": first_present(row, "id"),
        "createUser": first_present(row, "create_user", "createUser"),
        "createTime": first_present(row, "create_time", "createTime"),
        "updateUser": first_present(row, "update_user", "updateUser"),
        "updateTime": first_present(row, "update_time", "updateTime"),
        "deptCode": first_present(row, "dept_code", "deptCode"),
        "isDeleted": first_present(row, "is_deleted", "isDeleted"),
        "createDept": first_present(row, "create_dept", "createDept"),
        "routeGuid": first_present(row, "route_guid", "routeGuid"),
        "parentDeviceGuid": first_present(row, "parent_device_guid", "parentDeviceGuid"),
        "deviceGuid": first_present(row, "device_guid", "deviceGuid"),
        "routeDescription": first_present(row, "route_description", "routeDescription"),
        "description": first_present(row, "description"),
        "fileGuid": first_present(row, "file_guid", "fileGuid"),
        "routeVersionType": first_present(row, "route_version_type", "routeVersionType"),
        "routeType": first_present(row, "route_type", "routeType"),
        "deviceType": first_present(row, "device_type", "deviceType"),
        "routeSource": first_present(row, "route_source", "routeSource"),
        "adaptedModel": first_present(row, "adapted_model", "adaptedModel"),
        "trackVersion": first_present(row, "track_version", "trackVersion"),
        "trackType": first_present(row, "track_type", "trackType"),
        "routeContent": first_present(row, "route_content", "routeContent"),
        "fileType": first_present(row, "file_type", "fileType"),
        "uploadSource": first_present(row, "upload_source", "uploadSource"),
    }


def nearest_airport(
    longitude: float | None,
    latitude: float | None,
    airports: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if longitude is None or latitude is None:
        return None
    nearest: dict[str, Any] | None = None
    nearest_distance = float("inf")
    for airport in airports:
        airport_longitude = as_float(first_present(airport, "longitude", "lng"))
        airport_latitude = as_float(first_present(airport, "latitude", "lat"))
        if airport_longitude is None or airport_latitude is None:
            continue
        radius = as_float(first_present(airport, "inspection_radius", "inspectionRadius")) or 3000.0
        distance = haversine(longitude, latitude, airport_longitude, airport_latitude)
        if distance <= radius and distance < nearest_distance:
            nearest = airport
            nearest_distance = distance
    return nearest


def haversine(longitude1: float, latitude1: float, longitude2: float, latitude2: float) -> float:
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


def has_coverage(row: dict[str, Any]) -> bool:
    for key in (
        "dockGuid",
        "dockName",
        "airportGuid",
        "airportName",
        "airport_uid",
        "airport_name",
        "机场uid",
        "机场名称",
    ):
        if row.get(key):
            return True
    value = row.get("covered", row.get("isCovered", row.get("是否覆盖")))
    return value is True or str(value) in {"1", "true", "True", "是", "已覆盖", "covered"}
