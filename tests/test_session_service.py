from typing import Any

from langchain_core.messages import AIMessage

from app.services.session_service import SessionService


class Overwrite:
    def __init__(self, value: Any) -> None:
        self.value = value


def test_extract_latest_ai_text_handles_langgraph_overwrite_messages() -> None:
    service = SessionService(agent=None)
    event = {"agent": {"messages": Overwrite([AIMessage(content="hello")])}}

    assert service._extract_latest_ai_text(event) == "hello"


def test_extract_latest_ai_text_ignores_non_sequence_overwrite_messages() -> None:
    service = SessionService(agent=None)
    event = {"agent": {"messages": Overwrite({"not": "a message list"})}}

    assert service._extract_latest_ai_text(event) is None


def test_normalize_event_returns_message_for_top_level_messages() -> None:
    service = SessionService(agent=None)
    event = {"messages": [AIMessage(content="resume answer")]}

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "message"
    assert normalized["content"] == "resume answer"
