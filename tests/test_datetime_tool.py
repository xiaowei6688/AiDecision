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
