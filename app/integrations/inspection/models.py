"""Validated command payloads for the inspection system."""

from typing import Any

from pydantic import BaseModel, Field, model_validator


class CreateInspectionPlanInput(BaseModel):
    plan_type: str = Field(min_length=1, alias="planType")
    plan_name: str = Field(min_length=1, max_length=200, alias="planName")
    inspect_start_time: str = Field(min_length=1, alias="inspectStartTime")
    inspect_end_time: str = Field(min_length=1, alias="inspectEndTime")
    plan_object_list: list[dict[str, Any]] = Field(min_length=1, alias="planObjectList")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def normalize_plan_objects(self) -> "CreateInspectionPlanInput":
        self.plan_object_list = [normalize_plan_object(item) for item in self.plan_object_list]
        for index, item in enumerate(self.plan_object_list):
            missing = [
                key
                for key in ("deviceGuid", "deviceName", "major", "parentDeviceGuid", "parentDeviceName")
                if _is_blank(item.get(key))
            ]
            if missing:
                raise ValueError(f"planObjectList[{index}] 缺少真实巡检对象字段：{', '.join(missing)}")
            if _looks_like_guessed_plan_object(item):
                raise ValueError(
                    f"planObjectList[{index}] 疑似使用名称冒充 GUID，请先调用 inspection_query_device_data 查询真实杆塔数据"
                )
        return self


class CreateInspectionWorkOrderInput(BaseModel):
    plan_guid: str = Field(min_length=1, alias="planGuid")
    priority: str | int
    major: str = Field(min_length=1)
    work_nature: str = Field(min_length=1, alias="workNature")
    is_cycle: str | int = Field(alias="isCycle")
    inspection_method: str = Field(min_length=1, alias="inspectionMethod")
    start_date: str = Field(min_length=1, alias="startDate")
    end_date: str = Field(min_length=1, alias="endDate")
    order_detail_list: list[dict[str, Any]] = Field(min_length=1, alias="orderDetailList")
    work_content: str = Field(min_length=1, max_length=100, alias="workContent")
    equip_sn: str | None = Field(default=None, alias="equipSn")
    flight_workers: str | list[str] | None = Field(default=None, alias="flightWorkers")
    photo_storage_type: str | None = Field(default=None, alias="photoStorageType")
    pano_shot: bool = Field(default=False, alias="panoShot")
    is_record: str | int | None = Field(default=None, alias="isRecord")
    is_terrain: bool = Field(default=False, alias="isTerrain")

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def validate_resource_requirements(self) -> "CreateInspectionWorkOrderInput":
        if self.inspection_method == "drone" and not self.equip_sn:
            raise ValueError("人工飞手无人机巡检必须提供 equipSn")
        return self


def normalize_plan_object(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "deviceGuid": _first_present(item, "tower_guid", "tower_uid", "deviceGuid", "towerGuid", "杆塔uid"),
        "deviceName": _first_present(
            item,
            "basic_tower_ledger_name",
            "tower_name",
            "towerName",
            "deviceName",
            "杆塔名称",
        ),
        "major": _first_present(item, "major", "majorName", "professional", "profession", "specialty", "专业"),
        "parentDeviceGuid": _first_present(item, "line_guid", "line_uid", "parentDeviceGuid", "lineGuid", "线路uid"),
        "parentDeviceName": _first_present(
            item,
            "basic_line_ledger_name",
            "line_name",
            "lineName",
            "parentDeviceName",
            "线路名称",
        ),
    }


def _first_present(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if not _is_blank(value):
            return value
    return None


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() == "")


def _looks_like_guessed_plan_object(item: dict[str, Any]) -> bool:
    device_guid = str(item.get("deviceGuid") or "").strip()
    device_name = str(item.get("deviceName") or "").strip()
    parent_guid = str(item.get("parentDeviceGuid") or "").strip()
    parent_name = str(item.get("parentDeviceName") or "").strip()
    return bool(device_guid and device_guid == device_name and parent_guid and parent_guid == parent_name)
