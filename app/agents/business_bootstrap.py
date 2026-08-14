from app.agents.business_agents import BusinessAgentRegistry, default_business_agent_registry
from app.integrations.bootstrap import register_business_agents

_BOOTSTRAPPED = False
_BOOTSTRAPPED_INTEGRATIONS: frozenset[str] | None = None


def bootstrap_business_agents(
    registry: BusinessAgentRegistry = default_business_agent_registry,
    enabled_integrations: list[str] | None = None,
) -> BusinessAgentRegistry:
    global _BOOTSTRAPPED, _BOOTSTRAPPED_INTEGRATIONS
    enabled = frozenset(name for name in (enabled_integrations or []) if name)
    if (
        registry is default_business_agent_registry
        and _BOOTSTRAPPED
        and (
            _BOOTSTRAPPED_INTEGRATIONS == enabled
            or enabled_integrations is None
        )
    ):
        return registry
    register_business_agents(registry, enabled_integrations)
    if registry is default_business_agent_registry:
        _BOOTSTRAPPED = True
        _BOOTSTRAPPED_INTEGRATIONS = enabled
    return registry
