from app.tools.base_tool import (
    _format_human_resume_for_tool,
    _slots_from_human_resume,
    _summary_from_human_resume,
)
from app.actions.schemas import ActionResult
from app.tools.dynamic_tools import build_agent_tools
from app.agents.state import merge_dict_state
from app.integrations.projections import project_action_result
from app.integrations.bootstrap import register_integrations, register_business_agents
from app.actions.executor import default_action_executor
from app.actions.policy import default_policy_engine
from app.actions.registry import default_action_registry
from app.agents.business_agents import BusinessAgentRegistry


class _FakeModel:
    """占位模型，仅用于构建动态工具，不触发 LLM 调用。"""


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
    register_integrations(default_action_registry, default_action_executor, default_policy_engine)
    tools = build_agent_tools(_FakeModel())

    names = {getattr(item, "name", "") for item in tools}

    assert "consult_business_agents" in names
    assert "create_execution_plan" in names
    assert "list_business_agents" in names
    assert "plan_business_collaboration" in names
    assert "run_business_collaboration" in names
    assert "inspection_query_plan_detail" in names
    assert "inspection_query_coverage" in names
    assert "inspection_build_work_order_fill_state" in names


def test_register_business_agents_can_be_restricted() -> None:
    registry = BusinessAgentRegistry()
    register_business_agents(registry, enabled_integrations=["inspection"])

    assert [agent.business_id for agent in registry.list()] == ["inspection"]


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

    assert project_action_result(result) == {}
