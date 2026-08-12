from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry
from app.integrations import crm, erp, hr, inspection


def register_integrations(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> None:
    """Register all enabled business system integrations."""

    inspection.register(registry, executor, policy_engine)
    erp.register(registry, executor, policy_engine)
    hr.register(registry, executor, policy_engine)


def register_business_agents(registry: BusinessAgentRegistry) -> None:
    """Register analysis capabilities without initializing action adapters."""

    inspection.register_business_agent(registry)
    erp.register_business_agent(registry)
    hr.register_business_agent(registry)
    crm.register_business_agent(registry)
