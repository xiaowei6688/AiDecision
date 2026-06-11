from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, ToolMessage

from app.services.context_compressor import (
    FACTS_HEADER,
    PROGRESS_HEADER,
    ContextCompressor,
)


def test_context_compressor_keeps_recent_messages_and_summarizes_old_ones() -> None:
    messages = [
        HumanMessage(id="h1", content="第1个问题"),
        AIMessage(id="a1", content="第1个回答"),
        HumanMessage(id="h2", content="第2个问题"),
        AIMessage(id="a2", content="第2个回答"),
        HumanMessage(id="h3", content="第3个问题"),
    ]
    compressor = ContextCompressor(recent_messages=2, summary_max_chars=2000)

    result = compressor.compress({"messages": messages, "summary": "已有摘要"})

    assert result.update is not None
    assert result.removed_count == 3
    assert "已有摘要" in result.update["summary"]
    assert "第1个问题" in result.update["summary"]
    assert "第2个问题" in result.update["summary"]
    assert len(result.update["messages"]) == 3
    assert all(isinstance(message, RemoveMessage) for message in result.update["messages"])
    assert result.update["metadata"]["context_compression"]["kept_messages"] == 2


def test_context_compressor_does_not_touch_short_context() -> None:
    compressor = ContextCompressor(recent_messages=4, summary_max_chars=2000)

    result = compressor.compress({"messages": [HumanMessage(id="h1", content="hello")]})

    assert result.update is None
    assert result.removed_count == 0


def test_confirmed_slots_render_into_facts_section() -> None:
    messages = [
        HumanMessage(id="h1", content="帮我规划会议"),
        AIMessage(id="a1", content="好的，我先确认参会人"),
        HumanMessage(id="h2", content="还有别的吗"),
    ]
    slots = {
        "attendees": {
            "name": "参会人",
            "value": "张三/李四",
            "confidence": 1.0,
            "source": "human_resume",
        },
        # 低置信度：仍在评估，不应进入【已确认事实】。
        "budget": {"name": "预算", "value": "50万", "confidence": 0.3},
    }
    compressor = ContextCompressor(recent_messages=1, summary_max_chars=4000)

    result = compressor.compress({"messages": messages, "slots": slots})

    summary = result.update["summary"]
    assert FACTS_HEADER in summary
    assert "参会人: 张三/李四" in summary
    assert "来源: human_resume" in summary
    # 评估中的预算不应被当成已确认事实泄露给子 Agent。
    assert "预算: 50万" not in summary.split(PROGRESS_HEADER)[0]


def test_framework_confirmation_and_orchestration_noise_dropped() -> None:
    messages = [
        HumanMessage(id="h1", content="分析这个决策"),
        # 纯编排：只有 tool_calls、没有文本，应被丢弃。
        AIMessage(
            id="a1",
            content="",
            tool_calls=[{"name": "task", "args": {}, "id": "t1"}],
        ),
        # 框架确认回执，应被丢弃。
        ToolMessage(id="t1", content="Dialogue state updated.", tool_call_id="c1"),
        HumanMessage(id="h2", content="继续"),
    ]
    compressor = ContextCompressor(recent_messages=1, summary_max_chars=4000)

    result = compressor.compress({"messages": messages})

    summary = result.update["summary"]
    assert "Dialogue state updated." not in summary
    assert "分析这个决策" in summary
    assert result.removed_count == 3


def test_trim_preserves_facts_section_when_over_budget() -> None:
    long_narrative = "用户说了很多话。" * 200
    messages = [
        HumanMessage(id="h1", content=long_narrative),
        AIMessage(id="a1", content="收到"),
        HumanMessage(id="h2", content="继续"),
    ]
    slots = {
        "goal": {
            "name": "目标",
            "value": "确定Q3路线图",
            "confidence": 1.0,
            "source": "human_resume",
        },
    }
    compressor = ContextCompressor(recent_messages=1, summary_max_chars=200)

    result = compressor.compress({"messages": messages, "slots": slots})

    summary = result.update["summary"]
    # 即使叙事被裁剪，已确认事实必须保住。
    assert FACTS_HEADER in summary
    assert "目标: 确定Q3路线图" in summary
    assert len(summary) <= 200 + len(f"{FACTS_HEADER}\n- 目标: 确定Q3路线图（来源: human_resume）")
