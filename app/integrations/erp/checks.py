from typing import Any

from app.actions.policy import PolicyEngine
from app.actions.schemas import ActionExecutionContext, ActionSpec


def register_checks(policy_engine: PolicyEngine) -> None:
    policy_engine.register_pre_check(
        "erp.material_id_present",
        _required_param("material_id"),
    )
    policy_engine.register_pre_check("erp.quantity_positive", _quantity_positive)


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


def _quantity_positive(
    action: ActionSpec,
    params: dict[str, Any],
    context: ActionExecutionContext,
) -> str | None:
    quantity = params.get("quantity")
    if not isinstance(quantity, int | float):
        return "quantity must be a number"
    if quantity <= 0:
        return "quantity must be greater than zero"
    return None
