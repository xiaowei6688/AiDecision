from app.agents.business_agents import BusinessAgentRegistry, default_business_agent_registry
from app.integrations.bootstrap import register_business_agents

_BOOTSTRAPPED = False


def bootstrap_business_agents(
    registry: BusinessAgentRegistry = default_business_agent_registry,
) -> BusinessAgentRegistry:
    global _BOOTSTRAPPED
    if registry is default_business_agent_registry and _BOOTSTRAPPED:
        return registry
    register_business_agents(registry)
    if registry is default_business_agent_registry:
        _BOOTSTRAPPED = True
    return registry
