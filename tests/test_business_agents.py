import pytest
from langchain_core.messages import AIMessage

from app.agents.business_agents import (
    BusinessAgentManifest,
    BusinessAgentRegistry,
    parse_business_advice,
)
from app.agents.business_bootstrap import bootstrap_business_agents
from app.tools.dynamic_tools import _consult_business_agent


def test_builtin_business_agents_describe_cross_system_capabilities() -> None:
    registry = bootstrap_business_agents(BusinessAgentRegistry())

    erp = registry.get("erp")

    assert {item.business_id for item in registry.list()} == {"crm", "erp", "hr", "inspection"}
    assert erp.action_prefixes == ("erp.",)
    assert "HR" in erp.cross_system_notes

    crm = registry.get("crm")
    assert crm.datasources == ()
    assert crm.action_prefixes == ()


def test_business_agent_registry_rejects_duplicate_ids() -> None:
    registry = BusinessAgentRegistry()
    manifest = BusinessAgentManifest(
        business_id="crm",
        title="CRM",
        description="客户管理",
        system_prompt="你是 CRM 业务 Agent。",
        datasources=("crm",),
        action_prefixes=("crm.",),
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
    registry = bootstrap_business_agents(BusinessAgentRegistry())
    result = await _consult_business_agent(
        _AdviceModel(
            '{"recommended_actions":[{"action_id":"hr.create_leave_request",'
            '"params":{},"rationale":"wrong system"}]}'
        ),
        registry.get("erp"),
        "采购物料",
        {},
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "BUSINESS_ADVICE_OUT_OF_SCOPE"
