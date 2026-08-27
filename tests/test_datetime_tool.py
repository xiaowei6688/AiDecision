from datetime import datetime

import pytest

from app.tools.datetime_tool import compute_datetime


def test_compute_datetime_resolves_tomorrow_in_business_timezone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.tools.datetime_tool._now",
        lambda tz: datetime(2026, 8, 17, 10, 0, 0, tzinfo=tz),
    )

    result = compute_datetime.invoke({
        "expression": "明天",
        "timezone": "Asia/Shanghai",
        "compare_to_today": True,
    })

    assert result["ok"] is True
    assert result["date"] == "2026-08-18"
    assert result["today"] == "2026-08-17"
    assert result["is_after_today"] is True


@pytest.mark.parametrize(
    ("expression", "expected_date"),
    [
        ("后天", "2026-08-19"),
        ("大后天", "2026-08-20"),
        ("下周三", "2026-08-26"),
        ("下个月三号", "2026-09-03"),
        ("下下个月10号", "2026-10-10"),
        ("明年三月20号", "2027-03-20"),
        ("本月二十号", "2026-08-20"),
        ("三号", "2026-08-03"),
    ],
)
def test_compute_datetime_resolves_colloquial_dates(
    monkeypatch: pytest.MonkeyPatch,
    expression: str,
    expected_date: str,
) -> None:
    monkeypatch.setattr(
        "app.tools.datetime_tool._now",
        lambda tz: datetime(2026, 8, 17, 10, 0, 0, tzinfo=tz),
    )

    result = compute_datetime.invoke({
        "expression": expression,
        "timezone": "Asia/Shanghai",
        "compare_to_today": True,
    })

    assert result["ok"] is True
    assert result["date"] == expected_date


@pytest.mark.parametrize(
    ("expression", "expected_start", "expected_end"),
    [
        ("本周", "2026-08-17 00:00:00", "2026-08-23 23:59:59"),
        ("下周", "2026-08-24 00:00:00", "2026-08-30 23:59:59"),
        ("下个月", "2026-09-01 00:00:00", "2026-09-30 23:59:59"),
        ("今年", "2026-01-01 00:00:00", "2026-12-31 23:59:59"),
        ("明年", "2027-01-01 00:00:00", "2027-12-31 23:59:59"),
    ],
)
def test_compute_datetime_resolves_colloquial_periods(
    monkeypatch: pytest.MonkeyPatch,
    expression: str,
    expected_start: str,
    expected_end: str,
) -> None:
    monkeypatch.setattr(
        "app.tools.datetime_tool._now",
        lambda tz: datetime(2026, 8, 17, 10, 0, 0, tzinfo=tz),
    )

    result = compute_datetime.invoke({
        "expression": expression,
        "timezone": "Asia/Shanghai",
        "compare_to_today": True,
    })

    assert result["ok"] is True
    assert result["time_span"]["start_datetime"] == expected_start
    assert result["time_span"]["end_datetime"] == expected_end


def test_compute_datetime_does_not_mark_current_period_as_before_today(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.tools.datetime_tool._now",
        lambda tz: datetime(2026, 8, 19, 10, 0, 0, tzinfo=tz),
    )

    result = compute_datetime.invoke({
        "expression": "本周",
        "timezone": "Asia/Shanghai",
        "compare_to_today": True,
    })

    assert result["ok"] is True
    assert result["is_before_today"] is False
    assert result["is_today"] is True


def test_compute_datetime_resolves_colloquial_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.tools.datetime_tool._now",
        lambda tz: datetime(2026, 8, 17, 10, 0, 0, tzinfo=tz),
    )

    result = compute_datetime.invoke({
        "expression": "明天下午三点",
        "timezone": "Asia/Shanghai",
        "compare_to_today": True,
    })

    assert result["ok"] is True
    assert result["datetime"] == "2026-08-18 15:00:00"


def test_compute_datetime_rejects_invalid_colloquial_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.tools.datetime_tool._now",
        lambda tz: datetime(2026, 8, 17, 10, 0, 0, tzinfo=tz),
    )

    result = compute_datetime.invoke({
        "expression": "下个月31号",
        "timezone": "Asia/Shanghai",
        "compare_to_today": True,
    })

    assert result["ok"] is False
    assert result["errorCode"] == "invalid_datetime_expression"
