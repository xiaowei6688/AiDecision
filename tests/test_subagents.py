from app.agents.middleware import SummaryInjectionMiddleware
from app.agents.roles.subagents import build_role_subagents


class _FakeModel:
    """占位模型，仅用于构建 SubAgent spec，不会真正调用。"""


def test_each_role_subagent_has_summary_injection_middleware() -> None:
    subagents = build_role_subagents(_FakeModel())

    assert subagents, "应至少构建一个角色 SubAgent"
    for spec in subagents:
        middleware = spec.get("middleware") or []
        assert any(
            isinstance(m, SummaryInjectionMiddleware) for m in middleware
        ), f"{spec['name']} 缺少 SummaryInjectionMiddleware，子 Agent 将看不到压缩历史"


def test_subagent_injection_uses_independent_instances() -> None:
    # 每个子 Agent 应持有自己的 middleware 实例，避免跨 Agent 共享可变状态。
    subagents = build_role_subagents(_FakeModel())

    instances = [
        m
        for spec in subagents
        for m in (spec.get("middleware") or [])
        if isinstance(m, SummaryInjectionMiddleware)
    ]

    assert len(instances) == len(subagents)
    assert len({id(m) for m in instances}) == len(instances)
