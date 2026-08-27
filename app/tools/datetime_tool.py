"""所有 Agent 共用的确定性、时区感知日期解析能力。"""

from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.tools import tool


DEFAULT_TIMEZONE = "Asia/Shanghai"
WEEKDAY_ALIASES = {
    "一": 0,
    "1": 0,
    "二": 1,
    "2": 1,
    "三": 2,
    "3": 2,
    "四": 3,
    "4": 3,
    "五": 4,
    "5": 4,
    "六": 5,
    "6": 5,
    "日": 6,
    "天": 6,
    "七": 6,
    "7": 6,
}
CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def resolve_datetime_expression(
    expression: str | None,
    timezone: str | None = None,
    *,
    compare_to_today: bool = False,
) -> dict[str, Any]:
    """确定性解析相对日期、中文日历日期或 ISO 日期表达式。"""

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
    span = _time_span(value, target)
    if span is not None:
        result["time_span"] = span
    if compare_to_today:
        today = _now(tz).date()
        compare_start = target.date()
        compare_end = target.date()
        if span is not None:
            compare_start = datetime.fromisoformat(span["start_datetime"]).date()
            compare_end = datetime.fromisoformat(span["end_datetime"]).date()
        result.update({
            "today": today.isoformat(),
            "is_before_today": compare_end < today,
            "is_today": compare_start <= today <= compare_end,
            "is_after_today": compare_start > today,
        })
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
    colloquial = _colloquial_datetime(text, tz)
    if colloquial is not None:
        return colloquial
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


def _colloquial_datetime(text: str, tz: ZoneInfo) -> datetime | None:
    week = _week_datetime(text, tz)
    if week is not None:
        return week
    month = _relative_month_datetime(text, tz)
    if month is not None:
        return month
    year = _relative_year_datetime(text, tz)
    if year is not None:
        return year
    return None


def _week_datetime(text: str, tz: ZoneInfo) -> datetime | None:
    match = re.search(r"(?P<prefix>本|这|上|下下|下)\s*周\s*(?P<weekday>[一二三四五六日天七1-7])?", text)
    if match is None:
        return None
    now = _now(tz)
    prefix = match.group("prefix")
    week_offset = {"上": -1, "本": 0, "这": 0, "下": 1, "下下": 2}[prefix]
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    weekday = match.group("weekday")
    if weekday:
        target = monday + timedelta(weeks=week_offset, days=WEEKDAY_ALIASES[weekday])
        return _with_text_time(target, text)
    return monday + timedelta(weeks=week_offset)


def _relative_month_datetime(text: str, tz: ZoneInfo) -> datetime | None:
    match = re.search(
        r"(?P<prefix>本|这|下下|下)(?:个)?月\s*(?:(?P<day>[零〇一二两三四五六七八九十\d]{1,3})\s*(?:日|号)?)?",
        text,
    )
    if match is None:
        return None
    now = _now(tz)
    month_offset = {"本": 0, "这": 0, "下": 1, "下下": 2}[match.group("prefix")]
    base = _add_months(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0), month_offset)
    day = _parse_number(match.group("day")) if match.group("day") else 1
    try:
        target = base.replace(day=day)
    except ValueError as exc:
        raise ValueError(f"无效日期：{text}") from exc
    return _with_text_time(target, text)


def _relative_year_datetime(text: str, tz: ZoneInfo) -> datetime | None:
    match = re.search(
        r"(?P<prefix>今年|明年)\s*"
        r"(?:(?P<month>[零〇一二两三四五六七八九十\d]{1,3})\s*月\s*"
        r"(?P<day>[零〇一二两三四五六七八九十\d]{1,3})\s*(?:日|号)?)?",
        text,
    )
    if match is None:
        return None
    now = _now(tz)
    year = now.year + (1 if match.group("prefix") == "明年" else 0)
    month = _parse_number(match.group("month")) if match.group("month") else 1
    day = _parse_number(match.group("day")) if match.group("day") else 1
    try:
        target = datetime(year, month, day, tzinfo=tz)
    except ValueError as exc:
        raise ValueError(f"无效日期：{text}") from exc
    return _with_text_time(target, text)


def _chinese_datetime(text: str, tz: ZoneInfo) -> datetime | None:
    match = re.search(
        r"(?:(?P<year>\d{4})\s*年\s*)?"
        r"(?P<month>[零〇一二两三四五六七八九十\d]{1,3})\s*月\s*"
        r"(?P<day>[零〇一二两三四五六七八九十\d]{1,3})\s*(?:日|号)?",
        text,
    )
    if match is None:
        match = re.search(r"(?P<day>[零〇一二两三四五六七八九十\d]{1,3})\s*(?:日|号)", text)
    if match is None:
        return None
    now = _now(tz)
    groups = match.groupdict()
    month = _parse_number(groups.get("month")) if groups.get("month") else now.month
    day = _parse_number(match.group("day"))
    try:
        target = datetime(
            int(groups.get("year") or now.year),
            month,
            day,
            tzinfo=tz,
        )
    except ValueError as exc:
        raise ValueError(f"无效日期：{text}") from exc
    return _with_text_time(target, text)


def _parse_number(value: str | None) -> int:
    text = (value or "").strip()
    if not text:
        raise ValueError("数字不能为空")
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if text.startswith("十"):
        return 10 + CHINESE_DIGITS.get(text[1:], 0)
    if "十" in text:
        left, right = text.split("十", 1)
        tens = CHINESE_DIGITS.get(left, 0)
        ones = CHINESE_DIGITS.get(right, 0) if right else 0
        return tens * 10 + ones
    if text in CHINESE_DIGITS:
        return CHINESE_DIGITS[text]
    raise ValueError(f"无法解析数字：{value}")


def _with_text_time(target: datetime, text: str) -> datetime:
    hour = _named_hour(text)
    if hour is None:
        return target.replace(hour=0, minute=0, second=0, microsecond=0)
    return target.replace(hour=hour, minute=0, second=0, microsecond=0)


def _named_hour(text: str) -> int | None:
    explicit = re.search(r"(?P<hour>[零〇一二两三四五六七八九十\d]{1,3})\s*点", text)
    if explicit is not None:
        hour = _parse_number(explicit.group("hour"))
        if hour < 0 or hour > 23:
            raise ValueError(f"无效时间：{text}")
        if ("下午" in text or "晚上" in text or "夜间" in text) and hour < 12:
            hour += 12
        return hour
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
    calendar_span = _calendar_span(text, target)
    if calendar_span is not None:
        return calendar_span
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


def _calendar_span(text: str, target: datetime) -> dict[str, str] | None:
    week_match = re.search(r"(?P<name>(?:本|这|上|下下|下)\s*周)(?!\s*[一二三四五六日天七1-7])", text)
    if week_match is not None:
        start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=6, hours=23, minutes=59, seconds=59)
        return _span(week_match.group("name").replace(" ", ""), start, end)

    month_match = re.search(r"(?P<name>(?:本|这|下下|下)(?:个)?月)(?!\s*[零〇一二两三四五六七八九十\d])", text)
    if month_match is not None:
        start = target.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day = calendar.monthrange(start.year, start.month)[1]
        end = start.replace(day=last_day, hour=23, minute=59, second=59)
        return _span(month_match.group("name").replace(" ", ""), start, end)

    year_match = re.search(r"(?P<name>今年|明年)(?!\s*[零〇一二两三四五六七八九十\d])", text)
    if year_match is not None:
        start = target.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        end = target.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=0)
        return _span(year_match.group("name"), start, end)
    return None


def _span(name: str, start: datetime, end: datetime) -> dict[str, str]:
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
