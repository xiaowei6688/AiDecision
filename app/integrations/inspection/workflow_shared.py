"""Shared parsing and response helpers for inspection workflows."""

from __future__ import annotations

import json
import re
from typing import Any


def coerce_mapping_argument(value: dict[str, Any] | str, name: str) -> dict[str, Any]:
    parsed = load_json_argument(value, name)
    if not isinstance(parsed, dict):
        raise TypeError(f"{name} 必须是对象")
    return parsed


def coerce_list_argument(
    value: list[dict[str, Any]] | str | None,
    name: str,
) -> list[dict[str, Any]]:
    if value is None:
        return []
    parsed = load_json_argument(value, name)
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise TypeError(f"{name} 必须是对象数组")
    return parsed


def coerce_string_list_argument(
    value: list[str] | str | None,
    name: str,
) -> list[str]:
    if value is None:
        return []
    parsed = load_json_argument(value, name)
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise TypeError(f"{name} 必须是字符串数组")
    return parsed


def load_json_argument(value: Any, name: str) -> Any:
    if not isinstance(value, str):
        return value
    candidate = value.strip()
    last_error: json.JSONDecodeError | None = None
    for _ in range(3):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            try:
                candidate = json.loads(f'"{candidate}"')
            except json.JSONDecodeError:
                break
            continue
        if isinstance(parsed, str) and parsed.strip().startswith(("{", "[")):
            candidate = parsed.strip()
            continue
        return parsed
    raise ValueError(f"{name} 不是有效的 JSON 字符串") from last_error


def first_row_value(rows: list[dict[str, Any]], *keys: str) -> Any:
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
    return None


def first_present(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        candidate = value.get(key)
        if candidate not in (None, ""):
            return candidate
    return None


def rows_from_text2sql_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in find_rows(result.get("data")) if isinstance(row, dict)]


def find_rows(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return []
    for key in ("rows", "records", "list"):
        rows = value.get(key)
        if isinstance(rows, list):
            return rows
    for key in ("data", "result"):
        nested_value = value.get(key)
        if nested_value is value:
            continue
        nested = find_rows(nested_value)
        if nested:
            return nested
    return []


def complete_plan_object(item: dict[str, Any]) -> bool:
    return all(
        not (
            item.get(key) is None
            or isinstance(item.get(key), str) and not item.get(key).strip()
        )
        for key in (
            "deviceGuid",
            "deviceName",
            "major",
            "parentDeviceGuid",
            "parentDeviceName",
        )
    )


def requested_tower_count(ranges: str) -> int | None:
    text = (ranges or "").strip()
    if not text or text in {"全部", "所有", "ALL", "all"}:
        return None
    range_match = re.search(r"(\d+)\s*(?:-|~|到|至)\s*(\d+)", text)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        if start > end:
            start, end = end, start
        return end - start + 1
    numbers = [int(value) for value in re.findall(r"\d+", text)]
    return len(set(numbers)) if numbers else None


def tower_range_invalid_message(
    parent_device_name: str,
    ranges: str,
    rows: list[dict[str, Any]],
) -> str | None:
    requested_count = requested_tower_count(ranges)
    if requested_count is None or requested_count <= len(rows):
        return None
    suggestion = f"是否需要帮您指定巡检1-{len(rows)}号杆塔，" if rows else ""
    return (
        f"{parent_device_name} 线路下仅查询到 {len(rows)} 基符合条件的杆塔，"
        f"少于您输入的范围“{ranges}”对应的 {requested_count} 基杆塔。"
        f"{suggestion}或者请您重新输入需要巡检的有效杆塔范围。"
    )


def as_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def error(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "errorCode": code,
        "error": message,
        "retryable": code == "upstream_error",
    }
