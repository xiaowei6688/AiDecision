from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage, RemoveMessage


@dataclass(frozen=True)
class CompressionResult:
    """压缩旧消息后返回状态更新."""

    update: dict[str, Any] | None
    removed_count: int = 0


class ContextCompressor:
    """逐字记录最近的消息，并将旧消息压缩为摘要."""

    def __init__(self, recent_messages: int, summary_max_chars: int) -> None:
        self._recent_messages = recent_messages
        self._summary_max_chars = summary_max_chars

    def compress(self, values: dict[str, Any]) -> CompressionResult:
        """返回删除旧消息并刷新摘要的更新."""

        messages = values.get("messages") or []
        if len(messages) <= self._recent_messages:
            return CompressionResult(update=None)

        old_messages = messages[: -self._recent_messages]
        kept_messages = messages[-self._recent_messages :]
        old_summary = values.get("summary") or ""
        new_summary = self._merge_summary(old_summary, old_messages)

        removable_messages = [
            RemoveMessage(id=message.id, content="")
            for message in old_messages
            if isinstance(message, BaseMessage) and message.id
        ]

        if not removable_messages:
            return CompressionResult(update={"summary": new_summary}, removed_count=0)

        metadata = dict(values.get("metadata") or {})
        metadata["context_compression"] = {
            "recent_messages": self._recent_messages,
            "removed_messages": len(removable_messages),
            "kept_messages": len(kept_messages),
        }

        return CompressionResult(
            update={
                "messages": removable_messages,
                "summary": new_summary,
                "metadata": metadata,
            },
            removed_count=len(removable_messages),
        )

    def _merge_summary(self, old_summary: str, messages: list[Any]) -> str:
        message_summary = self._summarize_messages(messages)
        if not message_summary:
            return self._trim_summary(old_summary)

        if old_summary:
            merged = f"{old_summary.rstrip()}\n\n[历史压缩]\n{message_summary}"
        else:
            merged = f"[历史压缩]\n{message_summary}"

        return self._trim_summary(merged)

    def _summarize_messages(self, messages: list[Any]) -> str:
        lines: list[str] = []
        for message in messages:
            if not isinstance(message, BaseMessage):
                continue
            content = self._content_to_text(message.content).strip()
            if not content:
                continue
            role = self._role_name(message)
            lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    def _content_to_text(self, content: Any) -> str:
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

    def _role_name(self, message: BaseMessage) -> str:
        role_map = {
            "human": "用户",
            "ai": "AI",
            "system": "系统",
            "tool": "工具",
        }
        return role_map.get(message.type, message.type)

    def _trim_summary(self, summary: str) -> str:
        if len(summary) <= self._summary_max_chars:
            return summary
        return summary[-self._summary_max_chars :].lstrip()
