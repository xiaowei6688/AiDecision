from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from app.services.context_compressor import ContextCompressor


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
