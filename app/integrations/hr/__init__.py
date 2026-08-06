from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.integrations.hr.actions import register_actions
from app.integrations.hr.adapter import ADAPTER_NAME, HrAdapter
from app.integrations.hr.checks import register_checks


def register(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> None:
    register_checks(policy_engine)
    register_actions(registry, adapter_name=ADAPTER_NAME)
    executor.register_adapter(ADAPTER_NAME, HrAdapter())
