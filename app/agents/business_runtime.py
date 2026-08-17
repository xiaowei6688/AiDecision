"""Runtime adapters for Business Agent implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agents.business_agents import BusinessAdvice, BusinessAgentManifest, parse_business_advice
from app.tools.broker import ToolAuditRecord, ToolBroker, ToolBrokerRequest
from app.integrations.direct_results import DirectActionResult


@dataclass(frozen=True)
class BusinessAgentInvocation:
    manifest: BusinessAgentManifest
    task: str
    context: dict[str, Any]
    available_actions: list[dict[str, Any]]
    available_tools: tuple[Any, ...] = ()
    tool_broker: ToolBroker | None = None
    allow_direct_results: bool = False


@dataclass(frozen=True)
class BusinessAgentRunResult:
    advice: BusinessAdvice | None = None
    tool_audit: tuple[ToolAuditRecord, ...] = ()
    direct_result: DirectActionResult | None = None


class BusinessAgentRuntime(Protocol):
    """Local implementation behind a BusinessAgentManifest."""

    async def invoke(self, invocation: BusinessAgentInvocation) -> BusinessAgentRunResult:
        """Return structured, non-executable advice for the requested business domain."""

    async def health(self) -> dict[str, Any]:
        """Return a lightweight local runtime availability report."""


class LocalLLMBusinessAgent:
    def __init__(self, model: BaseChatModel) -> None:
        self._model = model

    async def invoke(self, invocation: BusinessAgentInvocation) -> BusinessAgentRunResult:
        manifest = invocation.manifest
        tools_by_name = {
            tool.name: tool for tool in invocation.available_tools
        }
        payload = {
            "task": invocation.task,
            "context": invocation.context,
            "datasources": list(manifest.datasources),
            "available_actions": invocation.available_actions,
            "available_readonly_tools": [
                {
                    "name": tool.name,
                    "description": tool.description,
                }
                for tool in invocation.available_tools
            ],
            "cross_system_notes": manifest.cross_system_notes,
            "required_output": BusinessAdvice.model_json_schema(),
            "output_rules": (
                "需要核对事实时可以调用 available_readonly_tools 中的只读工具。"
                "工具调用完成后，只返回一个符合 required_output 的 JSON object，不要使用 Markdown，不要执行动作。"
                "只能推荐 datasources 中的数据源和 available_actions 中列出的 action_id。"
            ),
        }
        messages = [
            SystemMessage(content=manifest.system_prompt),
            HumanMessage(content=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        ]
        model = (
            self._model.bind_tools(list(invocation.available_tools))
            if invocation.available_tools
            else self._model
        )
        audit: list[ToolAuditRecord] = []
        for _ in range(6):
            response = await model.ainvoke(messages)
            messages.append(response)
            tool_calls = getattr(response, "tool_calls", None) or []
            if not tool_calls:
                return BusinessAgentRunResult(
                    advice=parse_business_advice(
                        _message_content_to_text(response.content)
                    ),
                    tool_audit=tuple(audit),
                )
            for call in tool_calls:
                name = call.get("name")
                if tools_by_name.get(name) is None:
                    raise ValueError(f"Business Agent requested unauthorized tool: {name}")
                if invocation.tool_broker is None:
                    raise RuntimeError("Business Agent read-only tools require ToolBroker")
                broker_result = await invocation.tool_broker.execute(
                    ToolBrokerRequest(
                        business_id=manifest.business_id,
                        tool_name=name,
                        arguments=call.get("args") or {},
                    ),
                    manifest.readonly_tool_names,
                )
                audit.append(broker_result.audit)
                if invocation.allow_direct_results and broker_result.direct_result is not None:
                    return BusinessAgentRunResult(
                        tool_audit=tuple(audit),
                        direct_result=broker_result.direct_result,
                    )
                messages.append(ToolMessage(
                    content=json.dumps(
                        broker_result.result,
                        ensure_ascii=False,
                        default=str,
                    ),
                    tool_call_id=call.get("id") or name,
                ))
        raise ValueError("Business Agent exceeded the read-only tool call limit")

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
