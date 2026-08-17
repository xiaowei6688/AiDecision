"""Model-free result projections owned by the inspection integration."""

from typing import Any

from app.integrations.direct_results import DirectActionResult


def inspection_work_order_direct_action(result: Any) -> DirectActionResult | None:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    state = result.get("workOrderFillState")
    if not isinstance(state, dict) or state.get("status") != "READY":
        return None
    params = state.get("executePayload")
    if not isinstance(params, dict):
        return None
    return DirectActionResult(
        action_id="inspection.create_work_order",
        params=params,
    )
