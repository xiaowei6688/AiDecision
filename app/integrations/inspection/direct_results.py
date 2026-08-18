"""Model-free result projections owned by the inspection integration."""

from typing import Any

from app.integrations.direct_results import DirectActionResult, DirectMessageResult, DirectResult


def inspection_work_order_direct_action(result: Any) -> DirectResult | None:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    state = result.get("workOrderFillState")
    if not isinstance(state, dict):
        return None
    if state.get("status") == "COMPLETED":
        return DirectMessageResult(
            message=str(result.get("finalSummary") or "该计划的巡检工单已全部创建完成。"),
            data={
                "status": "COMPLETED",
                "summary": result.get("summary"),
                "workOrderCount": result.get("workOrderCount"),
                "towerCount": result.get("towerCount"),
                "planName": result.get("planName"),
            },
        )
    if state.get("status") != "READY":
        return None
    params = state.get("executePayload")
    if not isinstance(params, dict):
        return None
    return DirectActionResult(
        action_id="inspection.create_work_order",
        params=params,
    )
