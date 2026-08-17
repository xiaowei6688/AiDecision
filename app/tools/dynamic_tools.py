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
from app.core.runtime_context import get_runtime_context


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
    available["continue_business_workflow"] = _build_continue_business_workflow_tool(
        model, plugin_context
    )
    available["run_business_collaboration"] = _build_run_business_collaboration_tool(model, plugin_context)
    available.update({item.name: item for item in plugin_context.tools.values()})
    return list(available.values())


def _build_continue_business_workflow_tool(
    model: BaseChatModel,
    plugin_context: PluginContext,
) -> Any:
    @tool
    async def continue_business_workflow() -> dict[str, Any]:
        """执行插件已完成路由的单业务 continuation。"""

        metadata = get_runtime_context().metadata
        continuation = metadata.get("business_continuation")
        if not isinstance(continuation, dict):
            return {
                "status": "failed",
                "error_code": "BUSINESS_CONTINUATION_MISSING",
                "message": "当前请求不包含业务续接任务。",
            }
        business_id = str(continuation.get("businessId") or "").strip()
        operation = str(continuation.get("operation") or "").strip()
        if not business_id or not operation:
            return {
                "status": "failed",
                "error_code": "INVALID_BUSINESS_CONTINUATION",
                "message": "业务续接任务缺少 businessId 或 operation。",
            }
        try:
            agent = plugin_context.business_agent_registry.get(business_id)
        except KeyError as exc:
            return {
                "status": "failed",
                "error_code": "UNKNOWN_BUSINESS_AGENT",
                "message": str(exc),
            }
        return await _consult_business_agent(
            model,
            agent,
            operation,
            continuation,
            plugin_context.action_registry,
            plugin_context.tools,
            plugin_context.tool_broker,
            allow_direct_results=True,
        )

    return continue_business_workflow


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
                    plugin_context.tools,
                    plugin_context.tool_broker,
                )
                for agent in selected
            ]
        )
        result: dict[str, Any] = {
            "status": "success",
            "task": task,
            "advice": advice,
        }
        progress = _tool_audit_progress(advice)
        if progress is not None:
            result["task_progress"] = progress
        return result

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
                    plugin_context.tools,
                    plugin_context.tool_broker,
                )
                for step in wave
            ])
            advice_by_agent.update({result["business_id"]: result for result in results})
        advice = [advice_by_agent[step.business_id] for step in validated.steps]
        result: dict[str, Any] = {
            "status": "success",
            "task": task,
            "plan": validated.model_dump(),
            "advice": advice,
        }
        progress = _tool_audit_progress(advice)
        if progress is not None:
            result["task_progress"] = progress
        return result

    return run_business_collaboration


async def _consult_business_agent(
    model: BaseChatModel,
    agent: BusinessAgentManifest,
    task: str,
    context: dict[str, Any],
    action_registry: Any,
    tool_registry: Any,
    tool_broker: Any,
    *,
    allow_direct_results: bool = False,
) -> dict[str, Any]:
    actions = [
        action.public_dict()
        for action in action_registry.list()
        if any(action.action_id.startswith(prefix) for prefix in agent.action_prefixes)
    ]
    try:
        readonly_tools = tuple(tool_registry.read_only(agent.readonly_tool_names))
        runtime = build_business_agent_runtime(agent, model)
        run_result = await runtime.invoke(BusinessAgentInvocation(
            manifest=agent,
            task=task,
            context=context,
            available_actions=actions,
            available_tools=readonly_tools,
            tool_broker=tool_broker,
            allow_direct_results=allow_direct_results,
        ))
    except (PermissionError, RuntimeError, ValueError) as exc:
        return {
            "business_id": agent.business_id,
            "title": agent.title,
            "status": "failed",
            "error_code": "INVALID_BUSINESS_ADVICE",
            "message": str(exc),
        }
    if run_result.direct_result is not None:
        direct_result = run_result.direct_result
        if not any(
            direct_result.action_id.startswith(prefix)
            for prefix in agent.action_prefixes
        ):
            return {
                "business_id": agent.business_id,
                "title": agent.title,
                "status": "failed",
                "error_code": "BUSINESS_DIRECT_RESULT_OUT_OF_SCOPE",
                "message": "业务工具返回了未授权的直出动作。",
            }
        try:
            action_registry.get(direct_result.action_id)
        except KeyError as exc:
            return {
                "business_id": agent.business_id,
                "title": agent.title,
                "status": "failed",
                "error_code": "BUSINESS_DIRECT_ACTION_NOT_FOUND",
                "message": str(exc),
            }
        return {
            "business_id": agent.business_id,
            "title": agent.title,
            "status": "success",
            "_framework": {
                "direct_action": direct_result.model_dump(),
            },
            "tool_audit": [record.model_dump() for record in run_result.tool_audit],
        }
    advice = run_result.advice
    if advice is None:
        return {
            "business_id": agent.business_id,
            "title": agent.title,
            "status": "failed",
            "error_code": "EMPTY_BUSINESS_ADVICE",
            "message": "业务 Agent 未返回建议或直出结果。",
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
    failed_tools = [
        record
        for record in run_result.tool_audit
        if record.status not in {"success", "completed"}
    ]
    if failed_tools:
        failed = failed_tools[0]
        evidence = failed.evidence if isinstance(failed.evidence, dict) else {}
        return {
            "business_id": agent.business_id,
            "title": agent.title,
            "status": "failed",
            "error_code": "BUSINESS_TOOL_FAILED",
            "message": evidence.get("error") or failed.summary or "业务事实核对失败。",
            "tool_audit": [record.model_dump() for record in run_result.tool_audit],
        }
    return {
        "business_id": agent.business_id,
        "title": agent.title,
        "status": "success",
        "advice": advice.model_dump(),
        "tool_audit": [record.model_dump() for record in run_result.tool_audit],
    }


def _tool_audit_progress(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    records = [
        record
        for result in results
        for record in result.get("tool_audit", [])
        if isinstance(record, dict)
    ]
    if not records:
        return None
    steps = [
        {
            "id": record.get("request_id"),
            "title": record.get("title") or "核对业务事实",
            "status": "completed" if record.get("status") == "success" else "failed",
            "summary": record.get("summary"),
            "data": {
                "businessId": record.get("business_id"),
                "toolName": record.get("tool_name"),
                "durationMs": record.get("duration_ms"),
            },
        }
        for record in records
    ]
    failed = next(
        (step["id"] for step in steps if step["status"] == "failed"),
        None,
    )
    return {
        "steps": steps,
        "currentStep": steps[-1]["id"],
        "completedSteps": [
            step["id"] for step in steps if step["status"] == "completed"
        ],
        "failedStep": failed,
        "nextStep": None,
        "summary": steps[-1]["summary"],
    }
