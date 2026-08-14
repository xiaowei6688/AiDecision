import pytest
from langchain_core.messages import AIMessage

from app.agents.business_agents import (
    BusinessCollaborationPlan,
    BusinessAgentManifest,
    BusinessAgentRegistry,
    collaboration_waves,
    parse_business_advice,
    validate_collaboration_plan,
)
from app.agents.business_bootstrap import bootstrap_business_agents
from app.agents.business_runtime import (
    BusinessAgentInvocation,
    build_business_agent_runtime,
)
from app.tools.dynamic_tools import _consult_business_agent
from app.integrations.bootstrap import IntegrationManager
from app.integrations.context import PluginContext


def test_framework_registers_the_inspection_business_agent() -> None:
    registry = bootstrap_business_agents(BusinessAgentRegistry())

    assert [agent.business_id for agent in registry.list()] == ["inspection"]


def test_disabled_plugin_is_not_registered() -> None:
    registry = bootstrap_business_agents(
        BusinessAgentRegistry(),
        enabled_integrations=["inventory"],
    )

    assert registry.list() == []


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
    assert inspection_context.integration_tools
    assert empty_context.integration_tools == []
    assert inspection_context.action_result_projections
    assert empty_context.action_result_projections == []


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
    result = await _consult_business_agent(
        _AdviceModel(
            '{"recommended_actions":[{"action_id":"finance.adjust_ledger",'
            '"params":{},"rationale":"wrong system"}]}'
        ),
        manifest,
        "采购物料",
        {},
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

    advice = await runtime.invoke(BusinessAgentInvocation(
        manifest=manifest,
        task="采购物料",
        context={},
        available_actions=[],
    ))

    assert advice.facts_and_constraints == ["库存不足"]


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
