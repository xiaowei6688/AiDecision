from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, RemoveMessage, ToolMessage

FACTS_HEADER = "【已确认事实】"
PROGRESS_HEADER = "【对话进展】"

# update_dialogue_state 工具每次都会回这条无信息量的确认，压缩时丢弃。
_NOISE_TOOL_CONTENTS = frozenset({"Dialogue state updated."})

# 进入【已确认事实】段的最低置信度。低于此值的槽位视为仍在评估，
# 不当成定论喂给子 Agent，避免“评估中”被误读为“已确认”。
_FACT_CONFIDENCE_THRESHOLD = 0.5


@dataclass(frozen=True)
class CompressionResult:
    """压缩旧消息后返回状态更新."""

    update: dict[str, Any] | None
    removed_count: int = 0


class ContextCompressor:
    """逐字记录最近的消息，并将旧消息压缩为摘要.

    摘要分两段：
    - 【已确认事实】：从结构化 slots 渲染，带状态语义，是子 Agent 可信赖的定论。
    - 【对话进展】：过滤掉框架确认与编排噪音后的叙事，描述“讨论到哪了”。
    """

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
        slots = values.get("slots") or {}
        new_summary = self._merge_summary(old_summary, old_messages, slots)

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

    def _merge_summary(
        self,
        old_summary: str,
        messages: list[Any],
        slots: dict[str, Any],
    ) -> str:
        progress = self._summarize_messages(messages)
        facts = self._render_facts(slots)

        # 叙事段累加历史，事实段每次从最新 slots 全量重渲染（slots 自身已是
        # 累积状态），避免事实重复堆叠。
        narrative = self._merge_narrative(old_summary, progress)

        sections: list[str] = []
        if facts:
            sections.append(f"{FACTS_HEADER}\n{facts}")
        if narrative:
            sections.append(f"{PROGRESS_HEADER}\n{narrative}")

        merged = "\n\n".join(sections)
        return self._trim_summary(merged, facts_block=facts)

    def _merge_narrative(self, old_summary: str, progress: str) -> str:
        previous = self._strip_facts_section(old_summary).strip()
        if not progress:
            return previous
        if previous:
            return f"{previous}\n\n[历史压缩]\n{progress}"
        return f"[历史压缩]\n{progress}"

    def _strip_facts_section(self, summary: str) -> str:
        """从旧 summary 中剥离事实段，只保留叙事，供下一轮重新拼装。"""
        if not summary:
            return ""
        text = summary
        if FACTS_HEADER in text:
            # 事实段在前，叙事段以 PROGRESS_HEADER 起始；取叙事段正文。
            if PROGRESS_HEADER in text:
                return text.split(PROGRESS_HEADER, 1)[1].strip()
            # 只有事实段、没有叙事段。
            return ""
        if PROGRESS_HEADER in text:
            return text.split(PROGRESS_HEADER, 1)[1].strip()
        return text

    def _render_facts(self, slots: dict[str, Any]) -> str:
        lines: list[str] = []
        for key, slot in slots.items():
            if not isinstance(slot, dict):
                continue
            confidence = slot.get("confidence")
            if isinstance(confidence, int | float) and confidence < _FACT_CONFIDENCE_THRESHOLD:
                continue
            name = slot.get("name") or key
            value = slot.get("value")
            if value is None or str(value).strip() == "":
                continue
            source = slot.get("source")
            suffix = f"（来源: {source}）" if source else ""
            lines.append(f"- {name}: {value}{suffix}")
        return "\n".join(lines)

    def _summarize_messages(self, messages: list[Any]) -> str:
        lines: list[str] = []
        for message in messages:
            if not isinstance(message, BaseMessage):
                continue
            if self._is_noise(message):
                continue
            content = self._content_to_text(message.content).strip()
            if not content:
                continue
            role = self._role_name(message)
            lines.append(f"- {role}: {content}")
        return "\n".join(lines)

    def _is_noise(self, message: BaseMessage) -> bool:
        """过滤对子 Agent 无价值的框架确认与纯编排消息。"""
        # 框架确认类工具回执（如 update_dialogue_state 的固定回执）。
        if isinstance(message, ToolMessage):
            text = self._content_to_text(message.content).strip()
            if text in _NOISE_TOOL_CONTENTS:
                return True
        # 纯编排 AI 消息：只有 tool_calls、没有面向用户的文本，
        # 表达的是“去委派给谁”，不是结论。
        if isinstance(message, AIMessage):
            text = self._content_to_text(message.content).strip()
            if not text and getattr(message, "tool_calls", None):
                return True
        return False

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

    def _trim_summary(self, summary: str, facts_block: str = "") -> str:
        if len(summary) <= self._summary_max_chars:
            return summary

        # 截断时优先保住【已确认事实】段——事实丢失比叙事丢失危险得多。
        # 从叙事段尾部裁剪，把预算尽量留给事实段。
        facts_section = f"{FACTS_HEADER}\n{facts_block}" if facts_block else ""
        if facts_section and len(facts_section) < self._summary_max_chars:
            remaining = self._summary_max_chars - len(facts_section) - len(f"\n\n{PROGRESS_HEADER}\n")
            narrative = self._strip_facts_section(summary)
            if remaining > 0 and narrative:
                trimmed_narrative = narrative[-remaining:].lstrip()
                return f"{facts_section}\n\n{PROGRESS_HEADER}\n{trimmed_narrative}"
            return facts_section

        # 没有事实段（或事实段本身已超预算）时，退回原先的尾部截断。
        return summary[-self._summary_max_chars :].lstrip()
