import json
from typing import Annotated, Any

from pydantic import ValidationError

from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.types import Command, interrupt

from app.actions.schemas import ActionExecutionContext, ActionResult
from app.agents.state import DialogueStage, HumanActionStatus
from app.adapters.text_to_sql import TextToSqlClient
from app.core.config import get_settings
from app.core.runtime_context import get_runtime_context
from app.domain.plan_store import default_plan_store
from app.domain.plans import ExecutionPlan, PlanStatus, validate_execution_plan


DEFAULT_HUMAN_ACTIONS = ["approve", "reject", "edit", "clarify"]
PROGRESS_STATUSES = {"pending", "running", "completed", "failed", "skipped"}


def _ensure_business_runtime() -> None:
    _plugin_context()


def _plugin_context() -> Any:
    context = get_runtime_context().plugin_context
    if context is None:
        raise RuntimeError("plugin context is required while executing Agent tools")
    return context


def _action_registry() -> Any:
    context = _plugin_context()
    return _plugin_context().action_registry


def _action_executor() -> Any:
    context = _plugin_context()
    return _plugin_context().action_executor


def _business_agent_registry() -> Any:
    context = _plugin_context()
    return _plugin_context().business_agent_registry


@tool
def update_dialogue_state(
    intent: str | None = None,
    dialogue_stage: str | None = None,
    summary: str | None = None,
    slots: dict[str, Any] | None = None,
    last_active_agent: str | None = None,
    domain_state: dict[str, Any] | None = None,
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
    if domain_state is not None:
        update["domain_state"] = domain_state
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


@tool
def update_task_progress(
    steps: list[dict[str, Any]],
    current_step: str | None = None,
    summary: str | None = None,
    *,
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """发布面向前端展示的通用任务进展。

    steps 中每项可包含 id/title/status/summary/data。只输出可展示进度，不输出隐藏推理。
    """

    normalized_steps = [_normalize_progress_step(index, step) for index, step in enumerate(steps)]
    progress = _build_task_progress(normalized_steps, current_step, summary)
    content = json.dumps({"task_progress": progress}, ensure_ascii=False, separators=(",", ":"))
    return Command(
        update={
            "metadata": {"task_progress": progress},
            "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
        }
    )


@tool
def list_business_actions(query: str = "", limit: int = 8) -> dict[str, Any]:
    """列出或检索当前 Agent 可调用的业务动作目录。"""

    _ensure_business_runtime()
    actions = (
        _action_registry().search(query, limit=limit)
        if query
        else _action_registry().list()[:limit]
    )
    return {
        "status": "success",
        "actions": [action.public_dict() for action in actions],
    }


@tool
def list_business_agents() -> dict[str, Any]:
    """列出可由主 Agent 调度的业务 Agent 能力目录。"""

    registry = _business_agent_registry()
    return {
        "status": "success",
        "business_agents": [agent.public_dict() for agent in registry.list()],
    }


@tool
async def create_execution_plan(goal: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    """创建并校验跨系统执行计划；只返回预览，不会查询或执行任何业务动作。"""

    _ensure_business_runtime()
    registry = _business_agent_registry()
    datasources = {
        datasource
        for agent in registry.list()
        for datasource in agent.datasources
    }
    try:
        plan = ExecutionPlan.model_validate({"goal": goal, "steps": steps})
        validated = validate_execution_plan(plan, _action_registry(), datasources)
    except (KeyError, ValueError, ValidationError) as exc:
        return {
            "status": "failed",
            "error_code": "INVALID_EXECUTION_PLAN",
            "message": str(exc),
        }
    runtime = get_runtime_context()
    await default_plan_store.put(validated, runtime.session_id)
    return {
        "status": "success",
        "plan": validated.model_dump(mode="json"),
        "plan_id": validated.plan_id,
        "requires_human_approval": any(step.kind == "action" for step in validated.steps),
    }


@tool
async def approve_execution_plan(plan_id: str, note: str | None = None) -> dict[str, Any]:
    """批准当前会话的计划；批准不会执行任何步骤。"""

    runtime = get_runtime_context()
    try:
        plan = await default_plan_store.get(plan_id, runtime.session_id)
        plan.approve(runtime.user_id, note)
        await default_plan_store.put(plan, runtime.session_id)
    except (KeyError, PermissionError, ValueError) as exc:
        return {"status": "failed", "error_code": "PLAN_APPROVAL_REJECTED", "message": str(exc)}
    return {"status": "success", "plan": plan.model_dump(mode="json")}


async def _execute_plan_step(
    plan: ExecutionPlan,
    step: Any,
    confirmation_token: str | None,
) -> dict[str, Any]:
    if step.kind == "query":
        settings = get_settings()
        result = TextToSqlClient(
            base_url=settings.text_to_sql_base_url,
            timeout_seconds=settings.text_to_sql_timeout_seconds,
        ).query(step.datasource, step.question, step.filters)
        return result
    runtime = get_runtime_context()
    context = ActionExecutionContext(
        user_id=runtime.user_id,
        user_roles=list(runtime.user_roles),
        session_id=runtime.session_id,
        metadata=runtime.metadata,
    )
    action_result = await _action_executor().execute(
        action_id=step.action_id,
        params=step.params,
        context=context,
        confirmation_token=confirmation_token,
        idempotency_key=step.idempotency_key,
    )
    return _action_result_to_dict(action_result)


@tool
async def execute_execution_plan(
    plan_id: str,
    confirmation_tokens: dict[str, str] | None = None,
) -> dict[str, Any]:
    """按依赖顺序执行已批准计划；遇到确认要求会暂停并返回 token。"""

    runtime = get_runtime_context()
    try:
        plan = await default_plan_store.get(plan_id, runtime.session_id)
    except (KeyError, PermissionError) as exc:
        return {"status": "failed", "error_code": "PLAN_NOT_FOUND", "message": str(exc)}
    if plan.status not in {PlanStatus.APPROVED, PlanStatus.WAITING_CONFIRMATION, PlanStatus.RUNNING}:
        return {"status": "failed", "error_code": "PLAN_NOT_APPROVED", "message": f"plan status: {plan.status}"}

    plan.status = PlanStatus.RUNNING
    completed = {step.step_id for step in plan.steps if step.status == PlanStatus.SUCCEEDED}
    tokens = confirmation_tokens or {}
    for step in plan.steps:
        if step.status == PlanStatus.SUCCEEDED:
            continue
        if not set(step.depends_on).issubset(completed):
            step.status = PlanStatus.SKIPPED
            step.result = {"error": "dependency did not succeed"}
            plan.status = PlanStatus.FAILED
            await default_plan_store.put(plan, runtime.session_id)
            break
        step.status = PlanStatus.RUNNING
        step.attempts += 1
        await default_plan_store.put(plan, runtime.session_id)
        result = await _execute_plan_step(plan, step, tokens.get(step.step_id))
        step.result = result
        if result.get("status") == "requires_confirmation":
            step.status = PlanStatus.WAITING_CONFIRMATION
            plan.status = PlanStatus.WAITING_CONFIRMATION
            await default_plan_store.put(plan, runtime.session_id)
            break
        if result.get("status") == "failed":
            step.status = PlanStatus.FAILED
            plan.status = PlanStatus.FAILED
            await default_plan_store.put(plan, runtime.session_id)
            break
        step.status = PlanStatus.SUCCEEDED
        completed.add(step.step_id)
        await default_plan_store.put(plan, runtime.session_id)
    else:
        plan.status = PlanStatus.SUCCEEDED
        await default_plan_store.put(plan, runtime.session_id)
    return {"status": "success", "plan": plan.model_dump(mode="json")}


@tool
def semantic_query(
    datasource: str,
    question: str,
) -> dict[str, Any]:
    """调用外部 text-to-sql 语义查询服务，查询指定 datasource 的数据。"""

    settings = get_settings()
    client = TextToSqlClient(
        base_url=settings.text_to_sql_base_url,
        timeout_seconds=settings.text_to_sql_timeout_seconds,
    )
    return client.query(
        datasource=datasource,
        question=question
    )


@tool
async def call_business_action(
    action_id: str,
    params: dict[str, Any],
    confirmation_token: str | None = None,
) -> dict[str, Any]:
    """按统一 ActionSpec 执行业务动作，并返回标准化执行结果。"""

    _ensure_business_runtime()
    runtime = get_runtime_context()
    context = ActionExecutionContext(
        user_id=runtime.user_id,
        user_roles=list(runtime.user_roles),
        session_id=runtime.session_id,
        metadata=runtime.metadata,
    )
    result = await _action_executor().execute(
        action_id=action_id,
        params=params,
        context=context,
        confirmation_token=confirmation_token,
    )
    payload = _action_result_to_dict(result)
    if payload.get("status") == "requires_confirmation" and payload.get("executionMode") == "frontend_callback":
        resume_value = interrupt(_frontend_callback_human_action(payload))
        return _frontend_callback_resume_result(payload, resume_value)
    return payload


def _action_result_to_dict(result: ActionResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status,
        "action_id": result.action_id,
        "message": result.message,
        "data": result.data,
        "error_code": result.error_code,
    }
    payload.update(_plugin_context().projections.project_action_result(result))
    return payload


def _frontend_callback_human_action(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": HumanActionStatus.PENDING,
        "question": payload.get("question") or payload.get("message") or "请确认是否继续",
        "allowed_actions": ["approve", "reject", "edit"],
        "recommended_action": "approve",
        "ui_type": "confirmation",
        "fields": [],
        "payload": payload,
    }


def _frontend_callback_resume_result(
    pending_payload: dict[str, Any],
    resume_value: Any,
) -> dict[str, Any]:
    if not isinstance(resume_value, dict):
        return {
            "status": "failed",
            "action_id": pending_payload.get("action_id"),
            "message": f"前端执行结果无效：{resume_value}",
            "data": {"pendingAction": pending_payload, "resume": resume_value},
            "error_code": "INVALID_FRONTEND_ACTION_RESULT",
        }
    action = resume_value.get("action")
    data = resume_value.get("data") if isinstance(resume_value.get("data"), dict) else {}
    if action == "reject":
        return {
            "status": "failed",
            "action_id": pending_payload.get("action_id"),
            "message": resume_value.get("content") or "用户已取消前端执行动作。",
            "data": {"pendingAction": pending_payload, "frontendResult": data},
            "error_code": "FRONTEND_ACTION_REJECTED",
        }
    if action == "approve" and "success" not in data and "status" not in data:
        data = {**data, "success": True}
    result = {
        "status": "success" if action == "approve" else "updated",
        "action_id": pending_payload.get("action_id"),
        "message": resume_value.get("content") or data.get("message") or "前端已返回业务动作结果。",
        "data": {
            "pendingAction": pending_payload,
            "frontendResult": data,
        },
    }
    projection = _plugin_context().projections.project_frontend_callback(
        pending_payload, resume_value
    )
    if projection:
        result.update(projection)
        if isinstance(projection.get("data"), dict):
            result["data"] = {
                **result.get("data", {}),
                **projection["data"],
            }
    return result


def _normalize_progress_step(index: int, step: dict[str, Any]) -> dict[str, Any]:
    step_id = step.get("id") or step.get("step_id") or f"step-{index + 1}"
    title = step.get("title") or step.get("name") or step.get("content") or str(step_id)
    status = str(step.get("status") or "pending").strip().lower()
    if status not in PROGRESS_STATUSES:
        status = "pending"
    normalized: dict[str, Any] = {
        "id": str(step_id),
        "title": str(title).strip()[:80],
        "status": status,
    }
    step_summary = step.get("summary")
    if isinstance(step_summary, str) and step_summary.strip():
        normalized["summary"] = step_summary.strip()[:200]
    data = step.get("data")
    if isinstance(data, dict):
        normalized["data"] = data
    return normalized


def _build_task_progress(
    steps: list[dict[str, Any]],
    current_step: str | None,
    summary: str | None,
) -> dict[str, Any]:
    current = current_step or _current_progress_step_id(steps)
    completed = [step["id"] for step in steps if step.get("status") == "completed"]
    failed = next((step["id"] for step in steps if step.get("status") == "failed"), None)
    pending_or_running = [step for step in steps if step.get("status") in {"pending", "running"}]
    next_step = next((step["id"] for step in pending_or_running if step["id"] != current), None)
    progress: dict[str, Any] = {
        "steps": steps,
        "currentStep": current,
        "completedSteps": completed,
        "failedStep": failed,
        "nextStep": next_step,
    }
    if isinstance(summary, str) and summary.strip():
        progress["summary"] = summary.strip()[:200]
    return progress


def _current_progress_step_id(steps: list[dict[str, Any]]) -> str | None:
    running = next((step["id"] for step in steps if step.get("status") == "running"), None)
    if running:
        return running
    incomplete = next((step["id"] for step in steps if step.get("status") == "pending"), None)
    if incomplete:
        return incomplete
    if steps:
        return steps[-1]["id"]
    return None


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


AGENT_TOOLS = [
    update_dialogue_state,
    request_human_input,
    update_task_progress,
    list_business_actions,
    list_business_agents,
    create_execution_plan,
    approve_execution_plan,
    execute_execution_plan,
    semantic_query,
    call_business_action,
]
DST_TOOLS = AGENT_TOOLS
HUMAN_INPUT_TOOLS = [request_human_input]
