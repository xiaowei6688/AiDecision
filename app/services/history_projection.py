"""将通用会话历史投影为不同客户端协议。"""

from __future__ import annotations

from typing import Any


def project_legacy_session_history(
    session_id: str,
    history: list[dict[str, Any]],
    *,
    intent: str | None = None,
    dialogue_stage: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    """返回旧版前端使用的分组消息结构。

    该投影只转换通用消息字段，不了解任何业务插件或 Agent。
    """

    messages = [
        _project_legacy_message(message, sequence_no=index)
        for index, message in enumerate(history, start=1)
    ]
    created_at = next(
        (
            message["timestamp"]
            for message in messages
            if isinstance(message.get("timestamp"), str)
        ),
        None,
    )
    return {
        "session_id": session_id,
        "exists": bool(messages),
        "history": [{
            "version": None,
            "created_at": created_at,
            "messages": messages,
            "intent": intent,
            "dialogue_stage": dialogue_stage,
            "summary": summary,
        }] if messages else [],
    }


def _project_legacy_message(message: dict[str, Any], *, sequence_no: int) -> dict[str, Any]:
    metadata = message.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    role = _legacy_role(message.get("role"), message.get("type"))
    message_type = metadata.get("message_type")
    if not isinstance(message_type, str) or not message_type:
        message_type = "normal" if role == "human" else "message"

    return {
        "message_id": message.get("message_id"),
        "request_id": _optional_string(metadata.get("request_id")),
        "parent_message_id": _optional_string(metadata.get("parent_message_id")),
        "type": role,
        "role": role,
        "content": message.get("content"),
        "content_type": _optional_string(metadata.get("content_type")) or "text",
        "message_type": message_type,
        "sequence_no": sequence_no,
        "metadata": metadata,
        "timestamp": _optional_string(metadata.get("timestamp")),
    }


def _legacy_role(role: Any, message_type: Any) -> str:
    value = role if isinstance(role, str) else message_type
    return {
        "user": "human",
        "human": "human",
        "assistant": "ai",
        "ai": "ai",
        "system": "system",
    }.get(value, "system")


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
