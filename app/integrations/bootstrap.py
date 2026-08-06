from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.integrations import erp, hr, inspection


def register_integrations(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> None:
    """Register all enabled business system integrations."""

    inspection.register(registry, executor, policy_engine)
    erp.register(registry, executor, policy_engine)
    hr.register(registry, executor, policy_engine)
