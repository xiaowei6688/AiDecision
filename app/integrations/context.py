"""Application-scoped capability context for business plugins."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry
from app.integrations.projections import ProjectionRegistry
from app.integrations.continuations import ContinuationRegistry
from app.integrations.tools import IntegrationToolRegistry
from app.integrations.websocket_actions import ActionResultHandlerRegistry
from app.tools.broker import ToolBroker
from app.tools.datetime_tool import compute_datetime


@dataclass
class PluginContext:
    """All capabilities exposed by one application instance.

    Keeping this object application-scoped prevents two differently configured
    FastAPI applications in one process from sharing plugin registrations.
    """

    action_registry: ActionRegistry = field(default_factory=ActionRegistry)
    policy_engine: PolicyEngine = field(default_factory=PolicyEngine)
    business_agent_registry: BusinessAgentRegistry = field(
        default_factory=BusinessAgentRegistry
    )
    tools: IntegrationToolRegistry = field(default_factory=IntegrationToolRegistry)
    projections: ProjectionRegistry = field(default_factory=ProjectionRegistry)
    action_results: ActionResultHandlerRegistry = field(
        default_factory=ActionResultHandlerRegistry
    )
    continuations: ContinuationRegistry = field(default_factory=ContinuationRegistry)
    action_executor: BusinessActionExecutor = field(init=False)
    tool_broker: ToolBroker = field(init=False)

    def __post_init__(self) -> None:
        self.tools.register(compute_datetime, read_only=True)
        self.tools.register_step(
            "compute_datetime",
            "核对日期时间",
            "正在根据当前日期和业务时区核对时间表达",
        )
        self.tools.register_step(
            "plan_business_collaboration",
            "规划业务协作",
            "正在梳理涉及的业务能力和执行顺序",
        )
        self.tools.register_step(
            "consult_business_agents",
            "核对业务规则",
            "正在调用对应业务能力核对事实和执行条件",
        )
        self.tools.register_step(
            "run_business_collaboration",
            "执行业务协作",
            "正在按依赖顺序汇总各业务系统的分析结果",
        )
        self.tools.register_step(
            "call_business_action",
            "准备业务确认",
            "正在校验待执行操作并生成确认信息",
        )
        self.action_executor = BusinessActionExecutor(
            registry=self.action_registry,
            policy_engine=self.policy_engine,
        )
        self.tool_broker = ToolBroker(self.tools)
