import pytest

from app.tools.base_tool import (
    call_business_action,
    update_task_progress,
    _format_human_resume_for_tool,
    _slots_from_human_resume,
    _summary_from_human_resume,
)
from app.actions.schemas import ActionResult
from app.tools.dynamic_tools import build_agent_tools
from app.agents.state import merge_dict_state
from app.integrations.inspection.ui import (
    inspection_action_result_projection,
    inspection_frontend_callback_resume_projection,
)
from app.integrations.projections import ProjectionRegistry
from app.integrations.tools import IntegrationToolRegistry
from app.integrations.bootstrap import IntegrationManager
from app.integrations.context import PluginContext
from app.core.runtime_context import RequestRuntimeContext, reset_runtime_context, set_runtime_context


class _FakeModel:
    """占位模型，仅用于构建动态工具，不触发 LLM 调用。"""


def test_plugin_tool_registry_rejects_name_conflicts() -> None:
    registry = IntegrationToolRegistry()
    first = type("PluginTool", (), {"name": "shared_query"})()
    second = type("PluginTool", (), {"name": "shared_query"})()

    registry.register(first)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(second)


def test_format_human_resume_for_tool_includes_user_content() -> None:
    content = _format_human_resume_for_tool(
        {
            "action": "clarify",
            "content": "会议主题是 Q3 产品规划，参会人张三、李四、王五。",
            "data": {"duration_minutes": 60},
        }
    )

    assert "动作: clarify" in content
    assert "会议主题是 Q3 产品规划" in content
    assert '"duration_minutes":60' in content


def test_summary_from_human_resume_uses_user_content() -> None:
    summary = _summary_from_human_resume(
        {
            "action": "clarify",
            "content": "会议主题是 Q3 产品规划。",
            "data": {},
        }
    )

    assert summary == "用户已补充人工交互信息：会议主题是 Q3 产品规划。"


def test_slots_from_human_resume_includes_response_and_data() -> None:
    slots = _slots_from_human_resume(
        {
            "action": "clarify",
            "content": "会议主题是 Q3 产品规划。",
            "data": {"duration_minutes": 60},
        }
    )

    assert slots["last_human_action"]["value"] == "clarify"
    assert slots["last_human_response"]["value"] == "会议主题是 Q3 产品规划。"
    assert slots["human_resume_duration_minutes"]["value"] == 60


def test_dynamic_tools_include_business_agent_consultation() -> None:
    context = PluginContext()
    IntegrationManager(["inspection"]).register_context(context)
    tools = build_agent_tools(_FakeModel(), plugin_context=context)

    names = {getattr(item, "name", "") for item in tools}

    assert "consult_business_agents" in names
    assert "create_execution_plan" in names
    assert "list_business_agents" in names
    assert "plan_business_collaboration" in names
    assert "run_business_collaboration" in names
    assert "update_task_progress" in names
    assert "inspection_query_plan_detail" in names
    assert "inspection_query_coverage" in names
    assert "inspection_build_work_order_fill_state" in names


def test_update_task_progress_returns_generic_progress_command() -> None:
    result = update_task_progress.invoke(
        {
            "name": "update_task_progress",
            "type": "tool_call",
            "id": "tool-call-1",
            "args": {
                "steps": [
                    {"id": "query", "title": "查询数据", "status": "completed"},
                    {"id": "confirm", "title": "生成确认信息", "status": "running"},
                ],
                "current_step": "confirm",
                "summary": "正在处理",
            },
        }
    )

    update = result.update
    progress = update["metadata"]["task_progress"]
    assert progress["currentStep"] == "confirm"
    assert progress["completedSteps"] == ["query"]
    assert progress["steps"] == [
        {"id": "query", "title": "查询数据", "status": "completed"},
        {"id": "confirm", "title": "生成确认信息", "status": "running"},
    ]
    assert "inspection" not in str(progress)


def test_register_business_agents_can_be_restricted() -> None:
    context = PluginContext()
    IntegrationManager(["inspection"]).register_context(context)

    assert [agent.business_id for agent in context.business_agent_registry.list()] == ["inspection"]


def test_dst_dict_updates_merge_without_losing_existing_facts() -> None:
    assert merge_dict_state(
        {"budget": {"value": "50万"}, "owner": {"value": "张三"}},
        {"deadline": {"value": "下周五"}},
    ) == {
        "budget": {"value": "50万"},
        "owner": {"value": "张三"},
        "deadline": {"value": "下周五"},
    }


def test_action_result_projection_defaults_to_empty_dict_without_plugins() -> None:
    result = ActionResult(
        status="success",
        action_id="demo.action",
        message="ok",
    )

    assert ProjectionRegistry().project_action_result(result) == {}


@pytest.mark.asyncio
async def test_frontend_callback_action_interrupts_until_frontend_result(monkeypatch: pytest.MonkeyPatch) -> None:
    interrupts: list[dict[str, object]] = []

    async def execute(**kwargs: object) -> ActionResult:
        return ActionResult(
            status="requires_confirmation",
            action_id="inspection.create_plan",
            message="请确认是否创建以下巡检计划",
            data={
                "action": {"title": "创建巡检计划"},
                "params": {"planName": "临时计划"},
                "confirmation_token": "token-1",
            },
        )

    def fake_interrupt(action: dict[str, object]) -> dict[str, object]:
        interrupts.append(action)
        return {
            "action": "approve",
            "content": "前端已创建巡检计划",
            "data": {
                "success": True,
                "id": "plan-1",
                "planGuid": "plan-1",
            },
        }

    context = PluginContext()
    IntegrationManager(["inspection"]).register_context(context)
    monkeypatch.setattr(context.action_executor, "execute", execute)
    monkeypatch.setattr("app.tools.base_tool._action_executor", lambda: context.action_executor)
    monkeypatch.setattr("app.tools.base_tool.interrupt", fake_interrupt)

    token = set_runtime_context(RequestRuntimeContext(plugin_context=context))
    try:
        result = await call_business_action.ainvoke({
            "action_id": "inspection.create_plan",
            "params": {"planName": "临时计划"},
        })
    finally:
        reset_runtime_context(token)

    assert interrupts[0]["payload"]["executionMode"] == "frontend_callback"
    assert interrupts[0]["payload"]["actionCode"] == "createPlan"
    assert interrupts[0]["payload"]["executeApi"] == "/plan/create"
    assert result["status"] == "success"
    assert result["message"] == "前端已创建巡检计划"
    assert result["data"]["frontendResult"]["planGuid"] == "plan-1"
    assert result["data"]["createdPlanGuid"] == "plan-1"
    assert result["data"]["final"] is True
    assert "明确发起创建工单" in result["data"]["nextUserAction"]
