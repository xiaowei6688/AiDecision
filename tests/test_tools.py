import asyncio
import json

from langchain_core.messages import AIMessage
import pytest
import app.tools.dynamic_tools as dynamic_tools

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
from app.core.progress import ProgressChannel, reset_progress_channel, set_progress_channel
from app.tools.broker import ToolBrokerRequest
from app.tools.dynamic_tools import _tool_audit_progress
from app.integrations.direct_results import DirectActionResult, DirectMessageResult
from app.agents.business_agents import BusinessAgentManifest


class _FakeModel:
    """占位模型，仅用于构建动态工具，不触发 LLM 调用。"""


def test_plugin_tool_registry_rejects_name_conflicts() -> None:
    registry = IntegrationToolRegistry()
    first = type("PluginTool", (), {"name": "shared_query"})()
    second = type("PluginTool", (), {"name": "shared_query"})()

    registry.register(first)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(second)


def test_business_agent_cannot_receive_non_readonly_tool() -> None:
    registry = IntegrationToolRegistry()
    value = type("PluginTool", (), {"name": "create_record"})()
    registry.register(value)

    with pytest.raises(ValueError, match="must be read-only"):
        registry.read_only(("create_record",))


@pytest.mark.asyncio
async def test_tool_broker_projects_completed_result_for_direct_forwarding() -> None:
    context = PluginContext()

    from langchain_core.tools import tool

    @tool
    def build_record() -> dict[str, object]:
        """组装记录。"""

        return {"ok": True, "payload": {"name": "record-1"}}

    context.tools.register(build_record, read_only=True)
    context.tools.register_direct_result(
        "build_record",
        lambda result: DirectActionResult(
            action_id="inventory.create_record",
            params=result["payload"],
        ),
    )
    token = set_runtime_context(RequestRuntimeContext(plugin_context=context))
    try:
        result = await context.tool_broker.execute(
            ToolBrokerRequest(
                business_id="inventory",
                tool_name="build_record",
                arguments={},
            ),
            ("build_record",),
        )
    finally:
        reset_runtime_context(token)

    assert result.direct_result is not None
    assert result.direct_result.action_id == "inventory.create_record"
    assert result.direct_result.params == {"name": "record-1"}


@pytest.mark.asyncio
async def test_tool_broker_uses_stable_display_step_id_for_same_arguments() -> None:
    context = PluginContext()

    from langchain_core.tools import tool

    @tool
    def query_stock(product: str) -> dict[str, object]:
        """查询库存。"""

        return {"product": product, "quantity": 3}

    context.tools.register(query_stock, read_only=True)
    context.tools.register_step("query_stock", "核对库存", "正在核对库存")
    progress_channel = ProgressChannel()
    runtime_token = set_runtime_context(RequestRuntimeContext(
        session_id="session-1",
        plugin_context=context,
    ))
    progress_token = set_progress_channel(progress_channel)
    try:
        for _ in range(2):
            await context.tool_broker.execute(
                ToolBrokerRequest(
                    business_id="inventory",
                    tool_name="query_stock",
                    arguments={"product": "绝缘子"},
                ),
                ("query_stock",),
            )
    finally:
        reset_progress_channel(progress_token)
        reset_runtime_context(runtime_token)

    events = []
    while True:
        event = progress_channel.receive_nowait()
        if event is None:
            break
        events.append(event)

    assert [event.status for event in events] == [
        "running",
        "completed",
        "running",
        "completed",
    ]
    assert len({event.step_id for event in events}) == 1


@pytest.mark.asyncio
async def test_tool_broker_uses_framework_direct_action_without_plugin_projector() -> None:
    context = PluginContext()

    from langchain_core.tools import tool

    @tool
    def build_record() -> dict[str, object]:
        """组装记录。"""

        return {
            "ok": True,
            "_framework": {
                "direct_action": {
                    "action_id": "inventory.create_record",
                    "params": {"name": "record-1"},
                }
            },
        }

    context.tools.register(build_record, read_only=True)
    token = set_runtime_context(RequestRuntimeContext(plugin_context=context))
    try:
        result = await context.tool_broker.execute(
            ToolBrokerRequest(
                business_id="inventory",
                tool_name="build_record",
                arguments={},
            ),
            ("build_record",),
        )
    finally:
        reset_runtime_context(token)

    assert result.direct_result is not None
    assert result.direct_result.action_id == "inventory.create_record"
    assert result.direct_result.params == {"name": "record-1"}


@pytest.mark.asyncio
async def test_tool_broker_injects_runtime_context_and_records_evidence() -> None:
    context = PluginContext()

    from langchain_core.tools import tool
    from app.core.runtime_context import get_runtime_context

    @tool
    def query_owner() -> dict[str, object]:
        """查询当前执行身份。"""

        runtime = get_runtime_context()
        return {"userId": runtime.user_id, "sessionId": runtime.session_id}

    context.tools.register(query_owner, read_only=True)
    token = set_runtime_context(RequestRuntimeContext(
        user_id="user-1",
        session_id="session-1",
        plugin_context=context,
    ))
    try:
        result = await context.tool_broker.execute(
            ToolBrokerRequest(
                business_id="inventory",
                tool_name="query_owner",
                arguments={},
            ),
            ("query_owner",),
        )
    finally:
        reset_runtime_context(token)

    assert result.result == {"userId": "user-1", "sessionId": "session-1"}
    assert result.audit.user_id == "user-1"
    assert result.audit.session_id == "session-1"
    assert result.audit.evidence == result.result


@pytest.mark.asyncio
async def test_tool_broker_emits_live_running_and_completed_progress() -> None:
    context = PluginContext()

    from langchain_core.tools import tool

    release = asyncio.Event()

    @tool
    async def query_stock() -> dict[str, object]:
        """查询商品库存。"""

        await release.wait()
        return {"available": 12}

    context.tools.register(query_stock, read_only=True)
    context.tools.register_step(
        "query_stock",
        "核对库存事实",
        "正在核对商品库存和可用数量",
    )
    channel = ProgressChannel()
    runtime_token = set_runtime_context(RequestRuntimeContext(
        session_id="session-live",
        plugin_context=context,
    ))
    progress_token = set_progress_channel(channel)
    try:
        execution = asyncio.create_task(context.tool_broker.execute(
            ToolBrokerRequest(
                business_id="inventory",
                tool_name="query_stock",
                arguments={},
            ),
            ("query_stock",),
        ))
        running = await asyncio.wait_for(channel.receive(), timeout=1)
        assert not execution.done()
        release.set()
        result = await execution
        completed = await asyncio.wait_for(channel.receive(), timeout=1)
    finally:
        reset_progress_channel(progress_token)
        reset_runtime_context(runtime_token)

    assert running.status == "running"
    assert completed.status == "completed"
    assert completed.step_id == running.step_id
    assert result.audit.request_id
    assert completed.data["durationMs"] >= 0
    assert "arguments" not in completed.data
    assert "evidence" not in completed.data


@pytest.mark.asyncio
async def test_tool_broker_emits_failed_progress_for_tool_error() -> None:
    context = PluginContext()

    from langchain_core.tools import tool

    @tool
    async def failing_query() -> dict[str, object]:
        """执行失败的只读查询。"""

        raise RuntimeError("query unavailable")

    context.tools.register(failing_query, read_only=True)
    channel = ProgressChannel()
    progress_token = set_progress_channel(channel)
    try:
        result = await context.tool_broker.execute(
            ToolBrokerRequest(
                business_id="inventory",
                tool_name="failing_query",
                arguments={},
            ),
            ("failing_query",),
        )
        running = await channel.receive()
        failed = await channel.receive()
    finally:
        reset_progress_channel(progress_token)

    assert running.status == "running"
    assert failed.status == "failed"
    assert failed.step_id == running.step_id
    assert result.audit.status == "failed"


def test_tool_audit_is_exposed_as_generic_task_progress() -> None:
    progress = _tool_audit_progress([{
        "tool_audit": [{
            "request_id": "request-1",
            "business_id": "inventory",
            "tool_name": "query_stock",
            "title": "核对库存事实",
            "summary": "正在核对商品库存和可用数量",
            "status": "success",
            "duration_ms": 12,
        }],
    }])

    assert progress is not None
    assert progress["currentStep"] == "request-1"
    assert progress["steps"][0]["status"] == "completed"
    assert progress["steps"][0]["data"]["businessId"] == "inventory"


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
    assert "continue_business_workflow" in names
    assert "create_execution_plan" in names
    assert "list_business_agents" in names
    assert "plan_business_collaboration" in names
    assert "run_business_collaboration" in names
    assert "update_task_progress" in names
    assert "compute_datetime" in names
    assert "inspection_query_plan_detail" in names
    assert "inspection_query_coverage" in names
    assert "inspection_query_work_order_detail" in names
    assert "inspection_query_work_order_resources" in names
    assert "inspection_build_plan_fill_state" in names
    assert "inspection_build_work_order_fill_state" in names


@pytest.mark.asyncio
async def test_multi_agent_collaboration_forwards_unique_terminal_direct_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = PluginContext()
    for business_id in ("inventory", "weather", "operations"):
        context.business_agent_registry.register(BusinessAgentManifest(
            business_id=business_id,
            title=business_id,
            description="测试 Agent",
            system_prompt="",
            datasources=(),
            action_prefixes=(f"{business_id}.",),
        ))

    async def consult(
        _model: object,
        agent: BusinessAgentManifest,
        _task: str,
        invocation_context: dict[str, object],
        *_args: object,
        allow_direct_results: bool = False,
    ) -> dict[str, object]:
        if agent.business_id == "operations":
            assert allow_direct_results is True
            assert set(invocation_context["upstream_advice"]) == {"inventory", "weather"}
            return {
                "business_id": agent.business_id,
                "status": "success",
                "_framework": {
                    "direct_action": {
                        "action_id": "operations.execute",
                        "params": {"ready": True},
                    }
                },
                "tool_audit": [],
            }
        assert allow_direct_results is False
        return {
            "business_id": agent.business_id,
            "status": "success",
            "advice": {"facts_and_constraints": [agent.business_id]},
            "tool_audit": [],
        }

    monkeypatch.setattr(dynamic_tools, "_consult_business_agent", consult)
    run_tool = next(
        item
        for item in build_agent_tools(_FakeModel(), plugin_context=context)
        if item.name == "run_business_collaboration"
    )

    result = await run_tool.ainvoke({
        "task": "多系统准备后执行动作",
        "steps": [
            {"business_id": "inventory", "reason": "确认库存"},
            {"business_id": "weather", "reason": "确认天气"},
            {
                "business_id": "operations",
                "reason": "汇总前置条件并执行",
                "depends_on": ["inventory", "weather"],
            },
        ],
    })

    assert result["_framework"]["direct_action"] == {
        "action_id": "operations.execute",
        "params": {"ready": True},
    }


@pytest.mark.asyncio
async def test_business_continuation_routes_registered_handler_from_runtime_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ContinuationModel:
        def bind_tools(self, tools: list[object]) -> "ContinuationModel":
            return self

        async def ainvoke(self, messages: list[object]) -> AIMessage:
            raise AssertionError("registered continuation must not call the model")

    context = PluginContext()
    IntegrationManager(["inspection"]).register_context(context)
    continuation = {
        "businessId": "inspection",
        "operation": "create_work_orders_from_plan",
        "planId": "plan-1",
    }
    continuation_tool = next(
        item
        for item in build_agent_tools(ContinuationModel(), plugin_context=context)
        if item.name == "continue_business_workflow"
    )
    async def direct_handler(*_args: object) -> DirectMessageResult:
        return DirectMessageResult("来自真实业务查询的结果")

    monkeypatch.setattr(context.continuations, "dispatch", direct_handler)
    token = set_runtime_context(RequestRuntimeContext(
        session_id="session-1",
        metadata={"business_continuation": continuation},
        plugin_context=context,
    ))
    try:
        result = await continuation_tool.ainvoke({})
    finally:
        reset_runtime_context(token)

    assert result["status"] == "success"
    assert result["business_id"] == "inspection"
    assert result["message"] == "来自真实业务查询的结果"
    assert result["_framework"] == {"return_direct": True}


@pytest.mark.asyncio
async def test_business_continuation_forwards_registered_action_without_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DirectModel:
        def __init__(self) -> None:
            self.calls = 0

        def bind_tools(self, tools: list[object]) -> "DirectModel":
            return self

        async def ainvoke(self, messages: list[object]) -> AIMessage:
            self.calls += 1
            raise AssertionError("registered continuation must not call the model")

    model = DirectModel()
    context = PluginContext()
    IntegrationManager(["inspection"]).register_context(context)
    continuation_tool = next(
        item
        for item in build_agent_tools(model, plugin_context=context)
        if item.name == "continue_business_workflow"
    )
    async def direct_handler(*_args: object) -> DirectActionResult:
        return DirectActionResult(
            action_id="inspection.create_work_order",
            params={"orderDetailList": [{"deviceGuid": "tower-1"}]},
        )

    monkeypatch.setattr(context.continuations, "dispatch", direct_handler)
    token = set_runtime_context(RequestRuntimeContext(
        session_id="session-1",
        metadata={
            "business_continuation": {
                "businessId": "inspection",
                "operation": "create_work_orders_from_plan",
                "planId": "plan-1",
            }
        },
        plugin_context=context,
    ))
    try:
        result = await continuation_tool.ainvoke({})
    finally:
        reset_runtime_context(token)

    direct = result["_framework"]["direct_action"]
    assert model.calls == 0
    assert direct["action_id"] == "inspection.create_work_order"
    assert direct["params"]["orderDetailList"][0]["deviceGuid"] == "tower-1"


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
                "actionCode": "createPlan",
                "planId": "plan-1",
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
            "return_direct": True,
        })
    finally:
        reset_runtime_context(token)

    assert interrupts[0]["payload"]["executionMode"] == "frontend_callback"
    assert interrupts[0]["payload"]["actionCode"] == "createPlan"
    assert interrupts[0]["payload"]["executeApi"] == "/plan/create"
    assert result["status"] == "success"
    assert result["message"] == "前端已创建巡检计划"
    assert result["data"]["frontendResult"]["planId"] == "plan-1"
    assert result["data"]["createdPlanId"] == "plan-1"
    assert result["data"]["final"] is False
    assert result["data"]["businessContinuation"]["planId"] == "plan-1"
    assert result["_framework"] == {"return_direct": True}
