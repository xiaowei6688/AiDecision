import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool

from app.agents.business_agents import (
    BusinessCollaborationPlan,
    BusinessAgentManifest,
    BusinessAgentRegistry,
    collaboration_waves,
    parse_business_advice,
    validate_collaboration_plan,
)
from app.agents.business_runtime import (
    BusinessAgentInvocation,
    build_business_agent_runtime,
)
from app.tools.dynamic_tools import _consult_business_agent
from app.integrations.context import PluginContext
from app.actions.registry import ActionRegistry
from app.integrations.bootstrap import IntegrationManager


def test_framework_registers_the_inspection_business_agent() -> None:
    context = PluginContext()
    IntegrationManager(["inspection"]).register_context(context)

    assert [agent.business_id for agent in context.business_agent_registry.list()] == ["inspection"]


def test_disabled_plugin_is_not_registered() -> None:
    context = PluginContext()
    IntegrationManager(["inventory"]).register_context(context)

    assert context.business_agent_registry.list() == []


def test_plugin_contexts_are_isolated_per_application() -> None:
    inspection_context = PluginContext()
    IntegrationManager(["inspection"]).register_context(inspection_context)

    empty_context = PluginContext()
    IntegrationManager(["inventory"]).register_context(empty_context)

    assert inspection_context.business_agent_registry.contains("inspection")
    assert not empty_context.business_agent_registry.contains("inspection")
    assert inspection_context.action_registry.get("inspection.create_plan")
    with pytest.raises(KeyError):
        empty_context.action_registry.get("inspection.create_plan")
    assert len(inspection_context.tools) > 0
    assert [tool.name for tool in empty_context.tools.values()] == ["compute_datetime"]
    assert inspection_context.projections.counts()["action_results"] > 0
    assert empty_context.projections.counts()["action_results"] == 0


def test_business_agent_registry_rejects_duplicate_ids() -> None:
    registry = BusinessAgentRegistry()
    manifest = BusinessAgentManifest(
        business_id="sample.system",
        title="测试系统",
        description="测试业务 Agent",
        system_prompt="你是测试业务 Agent。",
        datasources=("sample",),
        action_prefixes=("sample.",),
    )
    registry.register(manifest)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(manifest)


def test_business_advice_requires_valid_json() -> None:
    with pytest.raises(ValueError, match="valid BusinessAdvice JSON"):
        parse_business_advice("建议先查询库存")


class _AdviceModel:
    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, messages: object) -> AIMessage:
        return AIMessage(content=self._content)


@pytest.mark.asyncio
async def test_business_advice_rejects_out_of_scope_actions() -> None:
    registry = BusinessAgentRegistry()
    manifest = BusinessAgentManifest(
        business_id="inventory",
        title="库存",
        description="测试 Agent",
        system_prompt="",
        datasources=("inventory",),
        action_prefixes=("inventory.",),
    )
    registry.register(manifest)
    context = PluginContext()
    result = await _consult_business_agent(
        _AdviceModel(
            '{"recommended_actions":[{"action_id":"finance.adjust_ledger",'
            '"params":{},"rationale":"wrong system"}]}'
        ),
        manifest,
        "采购物料",
        {},
        ActionRegistry(),
        context.tools,
        context.tool_broker,
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "BUSINESS_ADVICE_OUT_OF_SCOPE"


@pytest.mark.asyncio
async def test_local_business_agent_runtime_uses_structured_advice_contract() -> None:
    manifest = BusinessAgentManifest(
        business_id="inventory",
        title="库存",
        description="测试 Agent",
        system_prompt="",
        datasources=("inventory",),
        action_prefixes=("inventory.",),
    )
    runtime = build_business_agent_runtime(
        manifest,
        _AdviceModel('{"facts_and_constraints":["库存不足"]}'),
    )

    result = await runtime.invoke(BusinessAgentInvocation(
        manifest=manifest,
        task="采购物料",
        context={},
        available_actions=[],
    ))

    assert result.advice.facts_and_constraints == ["库存不足"]


@pytest.mark.asyncio
async def test_business_agent_can_call_authorized_readonly_tool() -> None:
    calls: list[str] = []

    @tool
    def query_stock(product: str) -> dict[str, object]:
        """查询库存。"""

        calls.append(product)
        return {"product": product, "quantity": 3}

    class ToolCallingModel:
        def __init__(self) -> None:
            self._responses = [
                AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "query_stock",
                        "args": {"product": "绝缘子"},
                        "id": "call-1",
                    }],
                ),
                AIMessage(content='{"facts_and_constraints":["库存为3"]}'),
            ]

        def bind_tools(self, tools: list[object]) -> "ToolCallingModel":
            assert [getattr(item, "name", None) for item in tools] == ["query_stock"]
            return self

        async def ainvoke(self, messages: object) -> AIMessage:
            return self._responses.pop(0)

    manifest = BusinessAgentManifest(
        business_id="inventory",
        title="库存",
        description="测试 Agent",
        system_prompt="",
        datasources=("inventory",),
        action_prefixes=("inventory.",),
        readonly_tool_names=("query_stock",),
    )
    runtime = build_business_agent_runtime(manifest, ToolCallingModel())
    context = PluginContext()
    context.tools.register(query_stock, read_only=True)

    result = await runtime.invoke(BusinessAgentInvocation(
        manifest=manifest,
        task="查询绝缘子库存",
        context={},
        available_actions=[],
        available_tools=(query_stock,),
        tool_broker=context.tool_broker,
    ))

    assert calls == ["绝缘子"]
    assert result.advice.facts_and_constraints == ["库存为3"]
    assert result.tool_audit[0].business_id == "inventory"
    assert result.tool_audit[0].evidence["quantity"] == 3


def test_business_collaboration_plan_builds_parallel_waves() -> None:
    registry = BusinessAgentRegistry()
    for business_id in ("people", "inventory", "operations"):
        registry.register(BusinessAgentManifest(
            business_id=business_id,
            title=business_id,
            description="测试 Agent",
            system_prompt="",
            datasources=(),
            action_prefixes=(),
        ))
    plan = BusinessCollaborationPlan.model_validate({
        "task": "协调多系统业务任务",
        "steps": [
            {"business_id": "people", "reason": "确认前置资源"},
            {"business_id": "inventory", "reason": "确认可用资源"},
            {
                "business_id": "operations",
                "reason": "根据前置约束制定操作方案",
                "depends_on": ["people", "inventory"],
            },
        ],
    })

    validated = validate_collaboration_plan(plan, registry)

    assert [[step.business_id for step in wave] for wave in collaboration_waves(validated)] == [
        ["people", "inventory"], ["operations"]
    ]


def test_business_collaboration_plan_rejects_cycles() -> None:
    registry = BusinessAgentRegistry()
    for business_id in ("a", "b"):
        registry.register(BusinessAgentManifest(
            business_id=business_id,
            title=business_id,
            description="测试 Agent",
            system_prompt="",
            datasources=(),
            action_prefixes=(),
        ))
    plan = BusinessCollaborationPlan.model_validate({
        "task": "invalid",
        "steps": [
            {"business_id": "a", "reason": "a", "depends_on": ["b"]},
            {"business_id": "b", "reason": "b", "depends_on": ["a"]},
        ],
    })

    with pytest.raises(ValueError, match="cycle"):
        validate_collaboration_plan(plan, registry)
