import json
from typing import Annotated, Any

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command, interrupt

from app.agents.state import DialogueStage, HumanActionStatus


DEFAULT_HUMAN_ACTIONS = ["approve", "reject", "edit", "clarify"]


@tool
def update_dialogue_state(
    intent: str | None = None,
    dialogue_stage: str | None = None,
    summary: str | None = None,
    slots: dict[str, Any] | None = None,
    last_active_agent: str | None = None,
    metadata: dict[str, Any] | None = None,
    *,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """理解对话后更新结构化DST字段."""

    update: dict[str, Any] = {}
    if intent is not None:
        update["intent"] = intent
    if dialogue_stage is not None:
        update["dialogue_stage"] = dialogue_stage
    if summary is not None:
        update["summary"] = summary
    if slots is not None:
        update["slots"] = slots
    if last_active_agent is not None:
        update["last_active_agent"] = last_active_agent
    if metadata is not None:
        update["metadata"] = metadata

    update["messages"] = [
        ToolMessage("Dialogue state updated.", tool_call_id=tool_call_id)
    ]

    return Command(update=update)


@tool
def request_human_input(
    question: str,
    reason: str,
    allowed_actions: list[str] | None = None,
    recommended_action: str = "clarify",
    ui_type: str = "form",
    fields: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
    *,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """暂停代理运行，并要求前端/用户做出决定。

    Args:
        question: 展示给用户的问题或确认文案。
        reason: 为什么需要人工介入。
        allowed_actions: 前端允许用户提交的动作。
        recommended_action: 推荐前端默认提交的动作，如 clarify/approve/reject/edit。
        ui_type: 推荐前端渲染方式，如 form/confirmation/editor/choice。
        fields: 当 ui_type=form 时，前端可渲染的字段描述。
        payload: 额外业务数据。
    """

    action = build_human_action(
        question=question,
        reason=reason,
        allowed_actions=allowed_actions,
        recommended_action=recommended_action,
        ui_type=ui_type,
        fields=fields,
        payload=payload,
    )
    resume_value = interrupt(action)

    return Command(
        update={
            "dialogue_stage": DialogueStage.COLLECTING_REQUIREMENTS,
            "pending_human_action": None,
            "summary": _summary_from_human_resume(resume_value),
            "slots": _slots_from_human_resume(resume_value),
            "metadata": {"last_human_resume": resume_value},
            "messages": [
                ToolMessage(
                    _format_human_resume_for_tool(resume_value),
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


def build_human_action(
    question: str,
    reason: str,
    allowed_actions: list[str] | None = None,
    recommended_action: str = "clarify",
    ui_type: str = "form",
    fields: list[dict[str, Any]] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """为 human-in-the-loop 中断构建前端口令."""

    actions = allowed_actions or DEFAULT_HUMAN_ACTIONS
    if recommended_action not in actions:
        actions = [*actions, recommended_action]

    return {
        "status": HumanActionStatus.PENDING,
        "question": question,
        "allowed_actions": actions,
        "recommended_action": recommended_action,
        "ui_type": ui_type,
        "fields": fields or [],
        "payload": {
            "reason": reason,
            **(payload or {}),
        },
    }


def _format_human_resume_for_tool(resume_value: Any) -> str:
    if not isinstance(resume_value, dict):
        return f"用户已回复人工交互请求：{resume_value}"

    lines = ["用户已回复人工交互请求。"]
    action = resume_value.get("action")
    content = resume_value.get("content")
    data = resume_value.get("data")

    if action:
        lines.append(f"动作: {action}")
    if content:
        lines.append(f"用户内容: {content}")
    if data:
        lines.append(
            "结构化数据: "
            + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        )

    return "\n".join(lines)


def _summary_from_human_resume(resume_value: Any) -> str:
    if isinstance(resume_value, dict):
        content = resume_value.get("content")
        if content:
            return f"用户已补充人工交互信息：{content}"
        action = resume_value.get("action")
        if action:
            return f"用户已对人工交互请求提交动作：{action}"

    return f"用户已回复人工交互请求：{resume_value}"


def _slots_from_human_resume(resume_value: Any) -> dict[str, dict[str, Any]]:
    slots: dict[str, dict[str, Any]] = {}
    if not isinstance(resume_value, dict):
        slots["last_human_response"] = {
            "name": "last_human_response",
            "value": resume_value,
            "confidence": 1.0,
            "source": "human_resume",
        }
        return slots

    action = resume_value.get("action")
    content = resume_value.get("content")
    data = resume_value.get("data")

    if action:
        slots["last_human_action"] = {
            "name": "last_human_action",
            "value": action,
            "confidence": 1.0,
            "source": "human_resume",
        }
    if content:
        slots["last_human_response"] = {
            "name": "last_human_response",
            "value": content,
            "confidence": 1.0,
            "source": "human_resume",
        }
    if isinstance(data, dict):
        for key, value in data.items():
            slots[f"human_resume_{key}"] = {
                "name": str(key),
                "value": value,
                "confidence": 1.0,
                "source": "human_resume",
            }

    return slots


DST_TOOLS = [update_dialogue_state, request_human_input]
HUMAN_INPUT_TOOLS = [request_human_input]
