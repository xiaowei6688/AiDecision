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
