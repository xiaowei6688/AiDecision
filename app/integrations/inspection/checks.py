"""Deterministic inspection business checks."""

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.actions.schemas import ActionExecutionContext, ActionSpec
from app.integrations.inspection.config import get_inspection_settings


def _today(timezone: str) -> datetime:
    return datetime.now(ZoneInfo(timezone))


def valid_time_window(
    action: ActionSpec,
    params: dict[str, Any],
    context: ActionExecutionContext,
) -> str | None:
    del action, context
    start = (
        params.get("inspectStartTime")
        or params.get("inspect_start_time")
        or params.get("startDate")
        or params.get("start_date")
    )
    end = (
        params.get("inspectEndTime")
        or params.get("inspect_end_time")
        or params.get("endDate")
        or params.get("end_date")
    )
    if not isinstance(start, str) or not isinstance(end, str):
        return "缺少开始或结束时间"
    try:
        timezone = ZoneInfo(get_inspection_settings().timezone)
        start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return "时间必须使用 ISO 兼容格式"
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone)
    else:
        start_time = start_time.astimezone(timezone)
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=timezone)
    else:
        end_time = end_time.astimezone(timezone)
    if end_time <= start_time:
        return "结束时间必须晚于开始时间"
    if start_time.date() < _today(str(timezone)).date():
        return "巡检开始日期不能早于今天"
    return None
