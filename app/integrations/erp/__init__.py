from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry
from app.integrations.erp.agent import register_business_agent
from app.integrations.erp.actions import register_actions
from app.integrations.erp.adapter import ADAPTER_NAME, ErpAdapter
from app.integrations.erp.checks import register_checks


def register(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> None:
    register_checks(policy_engine)
    register_actions(registry, adapter_name=ADAPTER_NAME)
    executor.register_adapter(ADAPTER_NAME, ErpAdapter())
