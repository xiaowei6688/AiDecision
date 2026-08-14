import asyncio
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import tool

from app.agents.business_agents import (
    BusinessCollaborationPlan,
    BusinessCollaborationStep,
    BusinessAgentManifest,
    collaboration_waves,
    validate_collaboration_plan,
)
from app.agents.business_runtime import BusinessAgentInvocation, build_business_agent_runtime
from app.tools.base_tool import AGENT_TOOLS
from app.integrations.context import PluginContext


def build_agent_tools(
    model: BaseChatModel,
    plugin_context: PluginContext | None = None,
) -> list[Any]:
    """Build tools that may need runtime dependencies such as the chat model."""

    if plugin_context is None:
        raise ValueError("plugin_context is required to build Agent tools")
    available = {tool.name: tool for tool in AGENT_TOOLS}
    available["plan_business_collaboration"] = _build_plan_business_collaboration_tool(plugin_context)
    available["consult_business_agents"] = _build_consult_business_agents_tool(model, plugin_context)
    available["run_business_collaboration"] = _build_run_business_collaboration_tool(model, plugin_context)
    available.update({item.name: item for item in plugin_context.tools.list()})
    return list(available.values())


def _build_plan_business_collaboration_tool(plugin_context: PluginContext) -> Any:
    @tool
    def plan_business_collaboration(
        task: str,
        steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """创建并校验业务 Agent 调度图；不调用 Agent，也不执行任何业务动作。"""

        registry = plugin_context.business_agent_registry
        try:
            plan = BusinessCollaborationPlan.model_validate({"task": task, "steps": steps})
            validated = validate_collaboration_plan(plan, registry)
            waves = collaboration_waves(validated)
        except (KeyError, ValueError) as exc:
            return {
                "status": "failed",
                "error_code": "INVALID_COLLABORATION_PLAN",
                "message": str(exc),
            }
        return {
            "status": "success",
            "plan": validated.model_dump(),
            "parallel_waves": [[step.business_id for step in wave] for wave in waves],
        }

    return plan_business_collaboration


def _build_consult_business_agents_tool(
    model: BaseChatModel, plugin_context: PluginContext
) -> Any:
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

        registry = plugin_context.business_agent_registry
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

        advice = await asyncio.gather(
            *[
                _consult_business_agent(
                    model,
                    agent,
                    task,
                    context or {},
                    plugin_context.action_registry,
                )
                for agent in selected
            ]
        )
        return {
            "status": "success",
            "task": task,
            "advice": advice,
        }

    return consult_business_agents


def _build_run_business_collaboration_tool(
    model: BaseChatModel, plugin_context: PluginContext
) -> Any:
    @tool
    async def run_business_collaboration(
        task: str,
        steps: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """按已校验调度图咨询业务 Agent；无依赖 Agent 并发，后续 Agent 接收前置建议。"""

        registry = plugin_context.business_agent_registry
        try:
            plan = BusinessCollaborationPlan.model_validate({"task": task, "steps": steps})
            validated = validate_collaboration_plan(plan, registry)
            waves = collaboration_waves(validated)
        except (KeyError, ValueError) as exc:
            return {
                "status": "failed",
                "error_code": "INVALID_COLLABORATION_PLAN",
                "message": str(exc),
            }

        action_registry = plugin_context.action_registry
        advice_by_agent: dict[str, dict[str, Any]] = {}
        for wave in waves:
            results = await asyncio.gather(*[
                _consult_business_agent(
                    model,
                    registry.get(step.business_id),
                    task,
                    {
                        **(context or {}),
                        "collaboration_reason": step.reason,
                        "upstream_advice": {
                            dependency: advice_by_agent[dependency]
                            for dependency in step.depends_on
                        },
                    },
                    action_registry,
                )
                for step in wave
            ])
            advice_by_agent.update({result["business_id"]: result for result in results})
        return {
            "status": "success",
            "task": task,
            "plan": validated.model_dump(),
            "advice": [advice_by_agent[step.business_id] for step in validated.steps],
        }

    return run_business_collaboration


async def _consult_business_agent(
    model: BaseChatModel,
    agent: BusinessAgentManifest,
    task: str,
    context: dict[str, Any],
    action_registry: Any,
) -> dict[str, Any]:
    actions = [
        action.public_dict()
        for action in action_registry.list()
        if any(action.action_id.startswith(prefix) for prefix in agent.action_prefixes)
    ]
    try:
        runtime = build_business_agent_runtime(agent, model)
        advice = await runtime.invoke(BusinessAgentInvocation(
            manifest=agent,
            task=task,
            context=context,
            available_actions=actions,
        ))
    except (RuntimeError, ValueError) as exc:
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
