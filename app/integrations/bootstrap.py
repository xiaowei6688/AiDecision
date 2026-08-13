from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry


def register_integrations(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> None:
    """Register all enabled business system integrations."""

    # Production integrations register their own actions here.


def register_business_agents(registry: BusinessAgentRegistry) -> None:
    """Extension hook for real local Business Agents.

    The framework intentionally ships with no registered business Agent.
    Each production integration registers its own local Agent here.
    """
