from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry
from app.integrations.inspection.agent import register_business_agent
from app.integrations.inspection.actions import register_actions
from app.integrations.inspection.adapter import ADAPTER_NAME, InspectionAdapter
from app.integrations.inspection.checks import register_checks


def register(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> None:
    register_checks(policy_engine)
    register_actions(registry, adapter_name=ADAPTER_NAME)
    executor.register_adapter(ADAPTER_NAME, InspectionAdapter())
