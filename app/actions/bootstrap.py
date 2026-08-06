from app.actions.executor import default_action_executor
from app.actions.policy import default_policy_engine
from app.actions.registry import default_action_registry
from app.integrations.bootstrap import register_integrations


_BOOTSTRAPPED = False


def bootstrap_actions() -> None:
    """Register enabled business integrations once."""

    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    register_integrations(
        registry=default_action_registry,
        executor=default_action_executor,
        policy_engine=default_policy_engine,
    )
    _BOOTSTRAPPED = True
