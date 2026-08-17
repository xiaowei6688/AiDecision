"""Application-scoped capability context for business plugins."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry
from app.integrations.projections import ProjectionRegistry
from app.integrations.tools import IntegrationToolRegistry
from app.integrations.websocket_actions import ActionResultHandlerRegistry
from app.tools.broker import ToolBroker


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
    action_executor: BusinessActionExecutor = field(init=False)
    tool_broker: ToolBroker = field(init=False)

    def __post_init__(self) -> None:
        self.action_executor = BusinessActionExecutor(
            registry=self.action_registry,
            policy_engine=self.policy_engine,
        )
        self.tool_broker = ToolBroker(self.tools)
