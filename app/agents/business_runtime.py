"""业务 Agent 实现的运行时适配器。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agents.business_agents import BusinessAdvice, BusinessAgentManifest, parse_business_advice
from app.tools.broker import ToolAuditRecord, ToolBroker, ToolBrokerRequest
from app.integrations.direct_results import DirectResult


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
    direct_result: DirectResult | None = None


class BusinessAgentRuntime(Protocol):
    """BusinessAgentManifest 背后的本地实现。"""

    async def invoke(self, invocation: BusinessAgentInvocation) -> BusinessAgentRunResult:
        """针对指定业务领域返回结构化、不可直接执行的建议。"""

    async def health(self) -> dict[str, Any]:
        """返回轻量级的本地运行时可用性报告。"""


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
        tool_result_cache: dict[tuple[str, str], Any] = {}
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
                arguments = call.get("args") or {}
                cache_key = (str(name), _canonical_args(arguments))
                if cache_key in tool_result_cache:
                    cached_result = tool_result_cache[cache_key]
                else:
                    broker_result = await invocation.tool_broker.execute(
                        ToolBrokerRequest(
                            business_id=manifest.business_id,
                            tool_name=name,
                            arguments=arguments,
                        ),
                        manifest.readonly_tool_names,
                    )
                    audit.append(broker_result.audit)
                    cached_result = broker_result.result
                    if broker_result.audit.status == "success":
                        tool_result_cache[cache_key] = cached_result
                    if invocation.allow_direct_results and broker_result.direct_result is not None:
                        return BusinessAgentRunResult(
                            tool_audit=tuple(audit),
                            direct_result=broker_result.direct_result,
                        )
                messages.append(ToolMessage(
                    content=json.dumps(
                        cached_result,
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
    """构建框架内所有业务 Agent 共用的本地运行时。"""

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


def _canonical_args(args: Any) -> str:
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return args.strip()
    return json.dumps(
        args or {},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
