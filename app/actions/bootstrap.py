from app.actions.executor import default_action_executor
from app.actions.policy import default_policy_engine
from app.actions.registry import default_action_registry
from app.integrations.bootstrap import register_integrations


_BOOTSTRAPPED = False
_BOOTSTRAPPED_INTEGRATIONS: frozenset[str] | None = None


def bootstrap_actions(enabled_integrations: list[str] | None = None) -> None:
    """Register the configured plugin actions once.

    The enabled set is deliberately passed in by the application boundary.  A
    model-facing tool must not decide which business plugins are active.
    """

    global _BOOTSTRAPPED, _BOOTSTRAPPED_INTEGRATIONS
    enabled = frozenset(name for name in (enabled_integrations or []) if name)
    if _BOOTSTRAPPED and (
        _BOOTSTRAPPED_INTEGRATIONS == enabled or enabled_integrations is None
    ):
        return

    register_integrations(
        registry=default_action_registry,
        executor=default_action_executor,
        policy_engine=default_policy_engine,
        enabled_integrations=list(enabled),
    )
    _BOOTSTRAPPED = True
    _BOOTSTRAPPED_INTEGRATIONS = enabled
