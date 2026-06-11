from app.tools.tools import (
    _format_human_resume_for_tool,
    _slots_from_human_resume,
    _summary_from_human_resume,
)


def test_format_human_resume_for_tool_includes_user_content() -> None:
    content = _format_human_resume_for_tool(
        {
            "action": "clarify",
            "content": "会议主题是 Q3 产品规划，参会人张三、李四、王五。",
            "data": {"duration_minutes": 60},
        }
    )

    assert "动作: clarify" in content
    assert "会议主题是 Q3 产品规划" in content
    assert '"duration_minutes":60' in content


def test_summary_from_human_resume_uses_user_content() -> None:
    summary = _summary_from_human_resume(
        {
            "action": "clarify",
            "content": "会议主题是 Q3 产品规划。",
            "data": {},
        }
    )

    assert summary == "用户已补充人工交互信息：会议主题是 Q3 产品规划。"


def test_slots_from_human_resume_includes_response_and_data() -> None:
    slots = _slots_from_human_resume(
        {
            "action": "clarify",
            "content": "会议主题是 Q3 产品规划。",
            "data": {"duration_minutes": 60},
        }
    )

    assert slots["last_human_action"]["value"] == "clarify"
    assert slots["last_human_response"]["value"] == "会议主题是 Q3 产品规划。"
    assert slots["human_resume_duration_minutes"]["value"] == 60
