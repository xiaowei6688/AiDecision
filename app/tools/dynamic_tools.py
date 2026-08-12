import json
import asyncio
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.actions.bootstrap import bootstrap_actions
from app.actions.registry import default_action_registry
from app.agents.business_bootstrap import bootstrap_business_agents
from app.agents.business_agents import (
    BusinessAgentManifest,
    parse_business_advice,
)
from app.tools.base_tool import AGENT_TOOLS


def build_agent_tools(model: BaseChatModel) -> list[Any]:
    """Build tools that may need runtime dependencies such as the chat model."""

    available = {tool.name: tool for tool in AGENT_TOOLS}
    available["consult_business_agents"] = _build_consult_business_agents_tool(model)
    return list(available.values())


def _build_consult_business_agents_tool(model: BaseChatModel) -> Any:
    @tool
    async def consult_business_agents(
        business_ids: list[str],
        task: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """并发咨询一个或多个业务 Agent，用于复杂业务判断和跨系统规划。

        每个业务 Agent 仅分析自身系统的事实、约束、建议查询和建议动作；主 Agent
        负责汇总意见、消解冲突并通过统一工具完成真实查询或动作执行。
        """

        registry = bootstrap_business_agents()
        selected: list[BusinessAgentManifest] = []
        unknown: list[str] = []
        for business_id in dict.fromkeys(business_ids):
            try:
                selected.append(registry.get(business_id))
            except KeyError:
                unknown.append(business_id)
        if unknown:
            return {
                "status": "failed",
                "message": "包含未知业务 Agent。",
                "unknown_business_ids": unknown,
                "available_business_agents": [item.public_dict() for item in registry.list()],
            }

        bootstrap_actions()
        advice = await asyncio.gather(
            *[_consult_business_agent(model, agent, task, context or {}) for agent in selected]
        )
        return {
            "status": "success",
            "task": task,
            "advice": advice,
        }

    return consult_business_agents


async def _consult_business_agent(
    model: BaseChatModel,
    agent: BusinessAgentManifest,
    task: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    actions = [
        action.public_dict()
        for action in default_action_registry.list()
        if any(action.action_id.startswith(prefix) for prefix in agent.action_prefixes)
    ]
    payload = {
        "task": task,
        "context": context,
        "datasources": list(agent.datasources),
        "available_actions": actions,
        "cross_system_notes": agent.cross_system_notes,
        "required_output": {
            "facts_and_constraints": ["业务域内事实和约束"],
            "assumptions": ["尚未验证的假设"],
            "recommended_queries": [{"datasource": "业务数据源", "question": "查询问题", "filters": {}}],
            "recommended_actions": [{"action_id": "已列出的动作", "params": {}, "rationale": "建议理由"}],
            "dependencies": ["其他业务系统的前后置依赖"],
            "risks": ["风险或需要人工确认的事项"],
            "missing_information": ["主 Agent 需要澄清的信息"],
        },
        "output_rules": (
            "只返回一个符合 required_output 的 JSON object，不要使用 Markdown，不要执行动作。"
            "只能推荐 datasources 中的数据源和 available_actions 中列出的 action_id。"
        ),
    }
    response = await model.ainvoke([
        SystemMessage(content=agent.system_prompt),
        HumanMessage(content=json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
    ])
    text = _message_content_to_text(response.content)
    try:
        advice = parse_business_advice(text)
    except ValueError as exc:
        return {
            "business_id": agent.business_id,
            "title": agent.title,
            "status": "failed",
            "error_code": "INVALID_BUSINESS_ADVICE",
            "message": str(exc),
        }
    invalid_sources = {
        query.datasource for query in advice.recommended_queries
    } - set(agent.datasources)
    invalid_actions = {
        action.action_id for action in advice.recommended_actions
        if not any(action.action_id.startswith(prefix) for prefix in agent.action_prefixes)
    }
    if invalid_sources or invalid_actions:
        return {
            "business_id": agent.business_id,
            "title": agent.title,
            "status": "failed",
            "error_code": "BUSINESS_ADVICE_OUT_OF_SCOPE",
            "message": "业务 Agent 建议了未授权的数据源或动作。",
            "invalid_datasources": sorted(invalid_sources),
            "invalid_action_ids": sorted(invalid_actions),
        }
    return {
        "business_id": agent.business_id,
        "title": agent.title,
        "status": "success",
        "advice": advice.model_dump(),
    }


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
