"""Inbound notification contracts for the inspection integration."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, model_validator

from app.schemas.chat import ServerEventType


class DetectResultNotification(BaseModel):
    workOrderId: str | int = Field(..., description="工单ID")
    workOrderNo: str | None = Field(default=None, description="工单编号")
    recognitionTaskGuid: str | None = Field(default=None, description="识别任务GUID")
    taskName: str
    relationSessionId: str
    totalPictures: int = Field(gt=0)
    defectPictures: int = Field(ge=0)
    totalDefects: int = Field(ge=0)
    normalDefects: int = Field(ge=0)
    seriousDefects: int = Field(ge=0)
    criticalDefects: int = Field(ge=0)


class StartFlyingNotification(BaseModel):
    workOrderId: str | int
    workOrderNo: str
    dockSn: str
    droneSn: str
    relationSessionId: str | None = Field(
        default=None,
        validation_alias=AliasChoices("relationSessionId", "sessionId", "session_id"),
    )


class InspectionNotificationRequest(BaseModel):
    type: Literal["recognizeCompleted", "startFlying"] = "recognizeCompleted"
    content: DetectResultNotification | StartFlyingNotification

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_payload(cls, data: Any) -> Any:
        if isinstance(data, dict) and "content" not in data:
            return {"type": "recognizeCompleted", "content": data}
        return data

    @model_validator(mode="after")
    def validate_content_matches_type(self) -> "InspectionNotificationRequest":
        if self.type == "recognizeCompleted" and not isinstance(self.content, DetectResultNotification):
            raise ValueError("recognizeCompleted 消息 content 必须是缺陷检测结果")
        if self.type == "startFlying" and not isinstance(self.content, StartFlyingNotification):
            raise ValueError("startFlying 消息 content 必须是无人机起飞信息")
        return self


def build_notification_event(request: InspectionNotificationRequest) -> dict[str, Any]:
    if isinstance(request.content, DetectResultNotification):
        return _build_detect_result_event(request.content)
    return _build_start_flying_event(request.content)


def _build_detect_result_event(content: DetectResultNotification) -> dict[str, Any]:
    message = _detect_result_summary(content)
    action = {
        "status": "pending",
        "question": message,
        "allowed_actions": ["detectResult", "cancel"],
        "actionCode": "openRecognitionTask",
        "actionName": "查看识别任务",
        "payload": {
            "reason": "巡检识别任务已完成，需要人工查看缺陷详情。",
            "buttonText": "查看缺陷详情",
            "needConfirm": False,
            "displayFields": {
                "workOrderId": content.workOrderId,
                "taskName": content.taskName,
                "totalDefects": content.totalDefects,
                "criticalDefects": content.criticalDefects,
                "seriousDefects": content.seriousDefects,
                "normalDefects": content.normalDefects,
            },
            "routePath": "/AI/recognition-chongqing/index",
            "executeApi": None,
            "executeMethod": None,
            "executePayload": {
                "recognitionTaskGuid": content.recognitionTaskGuid,
                "workOrderNo": content.workOrderNo,
            },
            "detectResult": content.model_dump(mode="json"),
        },
        "routePath": "/AI/recognition-chongqing/index",
        "executeApi": None,
        "executeMethod": None,
        "executePayload": {
            "recognitionTaskGuid": content.recognitionTaskGuid,
            "workOrderNo": content.workOrderNo,
        },
    }
    return {
        "type": ServerEventType.HUMAN_ACTION_REQUIRED.value,
        "session_id": content.relationSessionId,
        "content": message,
        "data": {"interrupts": [action]},
    }


def _build_start_flying_event(content: StartFlyingNotification) -> dict[str, Any]:
    message = f"工单编号为{content.workOrderNo}的巡检任务无人机已起飞！是否需要开启实时飞行监控？"
    action = {
        "status": "pending",
        "question": message,
        "allowed_actions": ["flyMonitor", "cancel"],
        "actionCode": "flightMonitoring",
        "actionName": "飞行监控",
        "payload": {
            "reason": "无人机起飞成功后，需要用户确认是否立即查看飞行监控。",
            "buttonText": "开启实时飞行监控",
            "needConfirm": False,
            "displayFields": {
                "workOrderId": content.workOrderId,
                "workOrderNo": content.workOrderNo,
                "dockSn": content.dockSn,
                "droneSn": content.droneSn,
            },
            "routePath": "/flightMonitoring/${dockSn}",
            "executeApi": "",
            "executeMethod": "",
            "executePayload": {"dockSn": [content.dockSn]},
            "startFlying": content.model_dump(mode="json"),
        },
        "routePath": "/flightMonitoring/${dockSn}",
        "executeApi": "",
        "executeMethod": "",
        "executePayload": {"dockSn": [content.dockSn]},
    }
    return {
        "type": ServerEventType.HUMAN_ACTION_REQUIRED.value,
        "session_id": content.relationSessionId,
        "content": message,
        "data": {"interrupts": [action]},
    }


def _detect_result_summary(content: DetectResultNotification) -> str:
    return (
        f"【巡检计划完成提醒】{date.today().isoformat()} {_task_title(content.taskName)}已全部完成\n"
        f"共识别缺陷 {content.totalDefects} 处\n"
        f"危急缺陷：{content.criticalDefects} 处\n"
        f"严重缺陷：{content.seriousDefects} 处\n"
        f"一般缺陷：{content.normalDefects} 处\n\n"
        f"工单编号：{content.workOrderId}\n"
        f"任务名称：{content.taskName}\n"
        f"图片总数：{content.totalPictures}\n"
        f"缺陷图片数：{content.defectPictures}\n"
    )


def _task_title(task_name: str) -> str:
    cleaned = task_name.strip()
    for suffix in ("巡检任务", "缺陷识别任务", "任务"):
        if cleaned.endswith(suffix):
            return cleaned[: -len(suffix)] + "巡检计划"
    return f"{cleaned}巡检计划"
