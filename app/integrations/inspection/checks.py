"""Deterministic inspection business checks."""

from datetime import datetime
from typing import Any

from app.actions.schemas import ActionExecutionContext, ActionSpec


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
        start_time = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_time = datetime.fromisoformat(end.replace("Z", "+00:00"))
    except ValueError:
        return "时间必须使用 ISO 兼容格式"
    if end_time <= start_time:
        return "结束时间必须晚于开始时间"
    return None
