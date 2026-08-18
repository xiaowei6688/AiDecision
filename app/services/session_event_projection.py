"""与具体业务无关的 Agent 事件投影辅助能力。"""

from __future__ import annotations

from collections.abc import Sequence
import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage


class SessionEventProjection:
    """解析运行时事件值，但不负责会话编排。"""

    def _extract_latest_ai_text(self, event: Any) -> str | None:
        if not isinstance(event, dict):
            return None

        for messages in self._message_sequences(event):
            if not messages:
                continue
            latest = messages[-1]
            if isinstance(latest, AIMessage):
                if getattr(latest, "tool_calls", None):
                    continue
                return self._message_content_to_text(latest.content)
        return None

    def _message_sequences(self, event: dict[str, Any]) -> list[Sequence[Any]]:
        candidates = [event.get("messages")]
        candidates.extend(
            value.get("messages")
            for value in event.values()
            if isinstance(value, dict)
        )

        sequences: list[Sequence[Any]] = []
        for candidate in candidates:
            messages = self._unwrap_langgraph_value(candidate)
            if isinstance(messages, Sequence) and not isinstance(messages, str | bytes):
                sequences.append(messages)
        return sequences

    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        return str(content)

    def _confirmation_interrupt_from_event(self, event: Any) -> dict[str, Any] | None:
        for candidate in self._candidate_dicts(event):
            if candidate.get("status") != "requires_confirmation":
                continue
            payload = self._confirmation_payload(candidate)
            if not payload:
                continue
            return {
                "question": candidate.get("question") or candidate.get("message") or "请确认是否继续",
                "allowed_actions": ["approve", "reject", "edit"],
                "recommended_action": "approve",
                "ui_type": "confirmation",
                "payload": payload,
            }
        return None

    def _confirmation_payload(self, candidate: dict[str, Any]) -> dict[str, Any]:
        data = candidate.get("data")
        data = data if isinstance(data, dict) else {}
        payload = {
            key: value
            for key, value in candidate.items()
            if key not in {"status", "message", "data", "error_code"}
        }
        if "confirmation_token" in data:
            payload["confirmation_token"] = data["confirmation_token"]
        if "params" in data:
            payload["params"] = data["params"]
        return payload

    def _candidate_dicts(self, value: Any) -> list[dict[str, Any]]:
        value = self._unwrap_langgraph_value(value)
        if isinstance(value, BaseMessage):
            content = self._message_content_to_text(value.content)
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return []
            return self._candidate_dicts(parsed)
        if isinstance(value, dict):
            candidates = [value]
            for item in value.values():
                candidates.extend(self._candidate_dicts(item))
            return candidates
        if isinstance(value, list | tuple):
            candidates: list[dict[str, Any]] = []
            for item in value:
                candidates.extend(self._candidate_dicts(item))
            return candidates
        return []

    def _jsonable(self, value: Any) -> Any:
        unwrapped = self._unwrap_langgraph_value(value)
        if unwrapped is not value:
            return self._jsonable(unwrapped)
        if isinstance(value, BaseMessage):
            return {
                "type": value.type,
                "content": self._message_content_to_text(value.content),
            }
        if isinstance(value, dict):
            return {str(key): self._jsonable(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._jsonable(item) for item in value]
        return self._stringify(value)

    def _unwrap_langgraph_value(self, value: Any) -> Any:
        if value.__class__.__name__ == "Overwrite" and hasattr(value, "value"):
            return value.value
        return value

    def _stringify(self, value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        return value
