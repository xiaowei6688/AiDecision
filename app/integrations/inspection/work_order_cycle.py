"""巡检工单周期字段的确定性组装。"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any


def normalize_work_order_cycle_fields(
    payload: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    """按旧巡检系统规则补全周期计划的工单字段。"""

    plan_type = str(plan.get("planType") or plan.get("plan_type") or "").strip()
    if plan_type == "5":
        payload["isCycle"] = "0"
        _remove_cycle_fields(payload)
        return

    cycle_type = {"1": "YEAR", "2": "MONTH", "3": "WEEK", "4": "DAY"}.get(plan_type)
    if cycle_type is None:
        payload["isCycle"] = "0"
        _remove_cycle_fields(payload)
        return

    start = _as_datetime(plan.get("inspectStartTime") or plan.get("inspect_start_time"))
    end = _as_datetime(plan.get("inspectEndTime") or plan.get("inspect_end_time")) or start
    if start is None:
        return
    if end < start:
        end = start

    payload["isCycle"] = "1"
    payload["workCycleType"] = cycle_type
    payload["cycleInspectStartTime"] = start.strftime("%H:%M:%S")
    payload["cycleInspectEndTime"] = end.strftime("%H:%M:%S")
    if cycle_type == "YEAR":
        _set_year(payload, start, end)
    elif cycle_type == "MONTH":
        _set_month(payload, start, end)
    elif cycle_type == "WEEK":
        _set_week(payload, start, end)
    else:
        _set_day(payload, start, end)


def _remove_cycle_fields(payload: dict[str, Any]) -> None:
    for key in (
        "workCycleType", "cycleStartDate", "cycleEndDate", "cycleInspectStartTime",
        "cycleInspectEndTime", "dayDates", "weekDays", "monthDays", "yearDates",
    ):
        payload.pop(key, None)


def _set_day(payload: dict[str, Any], start: datetime, end: datetime) -> None:
    payload["cycleStartDate"] = start.date().isoformat()
    payload["cycleEndDate"] = end.date().isoformat()
    payload["startDate"] = start.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    payload["endDate"] = end.replace(hour=23, minute=59, second=59, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    payload.setdefault("dayDates", _date_strings(start.date(), end.date()))
    for key in ("weekDays", "monthDays", "yearDates"):
        payload.pop(key, None)


def _set_week(payload: dict[str, Any], start: datetime, end: datetime) -> None:
    payload["cycleStartDate"] = start.date().isoformat()
    payload["cycleEndDate"] = end.date().isoformat()
    payload["startDate"] = start.replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    payload["endDate"] = end.replace(hour=23, minute=59, second=59, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    payload.setdefault("weekDays", sorted({item.isoweekday() for item in _dates(start.date(), end.date())}))
    for key in ("dayDates", "monthDays", "yearDates"):
        payload.pop(key, None)


def _set_month(payload: dict[str, Any], start: datetime, end: datetime) -> None:
    payload["cycleStartDate"] = start.strftime("%Y-%m")
    payload["cycleEndDate"] = end.strftime("%Y-%m")
    payload["startDate"] = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    payload["endDate"] = end.replace(day=monthrange(end.year, end.month)[1], hour=23, minute=59, second=59, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    payload.setdefault("monthDays", sorted({item.day for item in _dates(start.date(), end.date())}))
    for key in ("dayDates", "weekDays", "yearDates"):
        payload.pop(key, None)


def _set_year(payload: dict[str, Any], start: datetime, end: datetime) -> None:
    payload["cycleStartDate"] = str(start.year)
    payload["cycleEndDate"] = str(end.year)
    payload["startDate"] = start.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    payload["endDate"] = end.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    if not payload.get("yearDates"):
        dates: dict[int, list[int]] = {}
        for item in _dates(start.date(), end.date()):
            dates.setdefault(item.month, []).append(item.day)
        payload["yearDates"] = [{"month": month, "day": days} for month, days in sorted(dates.items())]
    for key in ("dayDates", "weekDays", "monthDays"):
        payload.pop(key, None)


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if not isinstance(value, str):
        return None
    text = value.strip().replace("T", " ")
    if len(text) == 10:
        text += " 00:00:00"
    try:
        return datetime.fromisoformat(text[:19])
    except ValueError:
        return None


def _dates(start: date, end: date) -> list[date]:
    if end < start:
        end = start
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _date_strings(start: date, end: date) -> list[str]:
    return [item.isoformat() for item in _dates(start, end)]
