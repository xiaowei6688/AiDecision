import json
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.actions.bootstrap import bootstrap_actions
from app.actions.registry import default_action_registry
from app.agents.roles.domain_experts import get_domain_expert, list_domain_experts
from app.tools.base_tool import AGENT_TOOLS


def build_agent_tools(model: BaseChatModel) -> list[Any]:
    """Build tools that may need runtime dependencies such as the chat model."""

    return [*AGENT_TOOLS, _build_consult_domain_expert_tool(model)]


def _build_consult_domain_expert_tool(model: BaseChatModel) -> Any:
    @tool
    async def consult_domain_expert(
        domain: str,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按需咨询指定业务领域专家，仅用于复杂、模糊、高风险或跨系统判断。"""

        expert = get_domain_expert(domain)
        if expert is None:
            return {
                "status": "failed",
                "message": "未知领域专家。",
                "available_experts": list_domain_experts(),
            }

        bootstrap_actions()
        actions = [
            action.public_dict()
            for action in default_action_registry.list()
            if action.system == expert.domain
        ]
        payload = {
            "task": task,
            "context": context or {},
            "available_actions": actions,
        }
        response = await model.ainvoke(
            [
                SystemMessage(content=expert.prompt),
                HumanMessage(
                    content=json.dumps(
                        payload,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                ),
            ]
        )

        return {
            "status": "success",
            "domain": expert.domain,
            "title": expert.title,
            "advice": _message_content_to_text(response.content),
        }

    return consult_domain_expert


def _message_content_to_text(content: Any) -> str:
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
