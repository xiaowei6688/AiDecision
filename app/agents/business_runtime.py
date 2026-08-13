"""Runtime adapters for Business Agent implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.business_agents import BusinessAdvice, BusinessAgentManifest, parse_business_advice


@dataclass(frozen=True)
class BusinessAgentInvocation:
    manifest: BusinessAgentManifest
    task: str
    context: dict[str, Any]
    available_actions: list[dict[str, Any]]


class BusinessAgentRuntime(Protocol):
    """Local implementation behind a BusinessAgentManifest."""

    async def invoke(self, invocation: BusinessAgentInvocation) -> BusinessAdvice:
        """Return structured, non-executable advice for the requested business domain."""

    async def health(self) -> dict[str, Any]:
        """Return a lightweight local runtime availability report."""


class LocalLLMBusinessAgent:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    async def invoke(self, invocation: BusinessAgentInvocation) -> BusinessAdvice:
        manifest = invocation.manifest
        payload = {
            "task": invocation.task,
            "context": invocation.context,
            "datasources": list(manifest.datasources),
            "available_actions": invocation.available_actions,
            "cross_system_notes": manifest.cross_system_notes,
            "required_output": BusinessAdvice.model_json_schema(),
            "output_rules": (
                "只返回一个符合 required_output 的 JSON object，不要使用 Markdown，不要执行动作。"
                "只能推荐 datasources 中的数据源和 available_actions 中列出的 action_id。"
            ),
        }
        response = await self._model.ainvoke([
            SystemMessage(content=manifest.system_prompt),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        ])
        return parse_business_advice(_message_content_to_text(response.content))

    async def health(self) -> dict[str, Any]:
        return {"status": "ready", "runtime": "local_llm"}


def build_business_agent_runtime(
    manifest: BusinessAgentManifest,
    model: BaseChatModel,
) -> BusinessAgentRuntime:
    """Build the local runtime used by every business Agent in this framework."""

    return LocalLLMBusinessAgent(model)


def _message_content_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return str(content)
