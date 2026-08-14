"""Application-scoped capability context for business plugins."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry


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
    integration_tools: list[Any] = field(default_factory=list)
    tool_steps: dict[str, Any] = field(default_factory=dict)
    action_result_projections: list[Any] = field(default_factory=list)
    human_interrupt_projections: list[Any] = field(default_factory=list)
    frontend_callback_projections: list[Any] = field(default_factory=list)
    action_result_handlers: list[Any] = field(default_factory=list)
    action_executor: BusinessActionExecutor = field(init=False)

    def __post_init__(self) -> None:
        self.action_executor = BusinessActionExecutor(
            registry=self.action_registry,
            policy_engine=self.policy_engine,
        )

    def register_tool(self, value: Any) -> None:
        if value not in self.integration_tools:
            self.integration_tools.append(value)

    def register_tool_step(self, name: str, description: Any) -> None:
        if name and description is not None:
            self.tool_steps[name] = description

    def register_projection(self, collection: list[Any], value: Any) -> None:
        if value not in collection:
            collection.append(value)

    def register_handler(self, value: Any) -> None:
        if value not in self.action_result_handlers:
            self.action_result_handlers.append(value)
