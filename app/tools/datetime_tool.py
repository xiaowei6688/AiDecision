"""Deterministic, timezone-aware date resolution shared by all Agents."""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool


DEFAULT_TIMEZONE = "Asia/Shanghai"


def _now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def resolve_datetime_expression(
    expression: str | None,
    timezone: str | None = None,
    *,
    compare_to_today: bool = False,
) -> dict[str, Any]:
    """Resolve a relative, Chinese calendar, or ISO expression deterministically."""

    tz = _resolve_timezone(timezone)
    value = (expression or "").strip()
    if not value:
        raise ValueError("时间表达不能为空")
    target = _parse_datetime(value, tz)
    result: dict[str, Any] = {
        "iso": target.isoformat(),
        "datetime": target.strftime("%Y-%m-%d %H:%M:%S"),
        "date": target.date().isoformat(),
        "timezone": str(target.tzinfo),
        "timestamp": int(target.timestamp()),
        "components": {
            "year": target.year,
            "month": target.month,
            "day": target.day,
            "hour": target.hour,
            "minute": target.minute,
            "second": target.second,
        },
    }
    if compare_to_today:
        today = _now(tz).date()
        result.update({
            "today": today.isoformat(),
            "is_before_today": target.date() < today,
            "is_today": target.date() == today,
            "is_after_today": target.date() > today,
        })
    span = _time_span(value, target)
    if span is not None:
        result["time_span"] = span
    return result


@tool
def compute_datetime(
    expression: str,
    timezone: str = DEFAULT_TIMEZONE,
    compare_to_today: bool = True,
    years: int = 0,
    months: int = 0,
    weeks: int = 0,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
) -> dict[str, Any]:
    """解析自然语言或 ISO 时间并执行偏移；相对日期禁止由模型自行计算。"""

    try:
        result = resolve_datetime_expression(
            expression,
            timezone,
            compare_to_today=compare_to_today,
        )
        tz = _resolve_timezone(timezone)
        target = datetime.fromisoformat(result["iso"])
        target = _add_months(target, years * 12 + months)
        target += timedelta(
            weeks=weeks,
            days=days,
            hours=hours,
            minutes=minutes,
            seconds=seconds,
        )
        if any((years, months, weeks, days, hours, minutes, seconds)):
            result = resolve_datetime_expression(
                target.astimezone(tz).isoformat(),
                timezone,
                compare_to_today=compare_to_today,
            )
        return {"ok": True, **result}
    except ValueError as exc:
        return {
            "ok": False,
            "errorCode": "invalid_datetime_expression",
            "error": str(exc),
            "retryable": True,
        }


def _resolve_timezone(value: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(value or DEFAULT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def _parse_datetime(text: str, tz: ZoneInfo) -> datetime:
    relative = _relative_datetime(text, tz)
    if relative is not None:
        return relative
    chinese = _chinese_datetime(text, tz)
    if chinese is not None:
        return chinese
    normalized = text.replace("/", "-")
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"无法解析时间表达：{text}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _relative_datetime(text: str, tz: ZoneInfo) -> datetime | None:
    normalized = text.strip().lower()
    offsets = (
        ("大后天", 3),
        ("后天", 2),
        ("明天", 1),
        ("今天", 0),
        ("昨天", -1),
        ("day after tomorrow", 2),
        ("tomorrow", 1),
        ("today", 0),
        ("yesterday", -1),
    )
    offset = next((days for marker, days in offsets if marker in normalized), None)
    if offset is None:
        return None
    target = _now(tz) + timedelta(days=offset)
    hour = _named_hour(text)
    if hour is not None:
        target = target.replace(hour=hour, minute=0, second=0, microsecond=0)
    return target.replace(microsecond=0)


def _chinese_datetime(text: str, tz: ZoneInfo) -> datetime | None:
    match = re.search(
        r"(?:(?P<year>\d{4})\s*年\s*)?"
        r"(?P<month>\d{1,2})\s*月\s*"
        r"(?P<day>\d{1,2})\s*(?:日|号)?",
        text,
    )
    if match is None:
        return None
    now = _now(tz)
    try:
        return datetime(
            int(match.group("year") or now.year),
            int(match.group("month")),
            int(match.group("day")),
            _named_hour(text) or 0,
            tzinfo=tz,
        )
    except ValueError as exc:
        raise ValueError(f"无效日期：{text}") from exc


def _named_hour(text: str) -> int | None:
    if "凌晨" in text:
        return 0
    if "上午" in text:
        return 9
    if "中午" in text or "下午" in text:
        return 12
    if "晚上" in text or "夜间" in text:
        return 20
    return None


def _time_span(text: str, target: datetime) -> dict[str, str] | None:
    periods = {
        "上午": (0, 11, 59, 59),
        "下午": (12, 23, 59, 59),
        "晚上": (18, 23, 59, 59),
        "夜间": (18, 23, 59, 59),
    }
    matched = next((item for item in periods.items() if item[0] in text), None)
    if matched is None:
        return None
    name, (start_hour, end_hour, end_minute, end_second) = matched
    start = target.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end = target.replace(
        hour=end_hour,
        minute=end_minute,
        second=end_second,
        microsecond=0,
    )
    return {
        "name": name,
        "start_datetime": start.strftime("%Y-%m-%d %H:%M:%S"),
        "end_datetime": end.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _add_months(value: datetime, months: int) -> datetime:
    total = value.month - 1 + months
    year = value.year + total // 12
    month = total % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)
