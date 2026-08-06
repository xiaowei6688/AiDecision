from typing import Any

from app.actions.policy import PolicyEngine
from app.actions.schemas import ActionExecutionContext, ActionSpec


def register_checks(policy_engine: PolicyEngine) -> None:
    policy_engine.register_pre_check(
        "inspection.device_id_present",
        _required_param("device_id"),
    )
    policy_engine.register_pre_check(
        "inspection.assignee_id_present",
        _required_param("assignee_id"),
    )


def _required_param(name: str) -> Any:
    def check(
        action: ActionSpec,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> str | None:
        if params.get(name) in (None, ""):
            return f"{name} is required"
        return None

    return check
