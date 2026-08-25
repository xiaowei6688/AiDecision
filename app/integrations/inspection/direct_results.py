"""Model-free result projections owned by the inspection integration."""

from typing import Any

from app.integrations.direct_results import DirectActionResult, DirectMessageResult, DirectResult
from app.integrations.inspection.work_order_summary import work_order_group


def inspection_work_order_direct_action(result: Any) -> DirectResult | None:
    if not isinstance(result, dict) or result.get("ok") is not True:
        return None
    state = result.get("workOrderFillState")
    if not isinstance(state, dict):
        return None
    if state.get("status") == "COMPLETED":
        created_work_orders = result.get("createdWorkOrders") or result.get("created_work_orders")
        if isinstance(created_work_orders, list):
            dock_orders = [
                item for item in created_work_orders
                if isinstance(item, dict)
                and _is_dock_work_order(item)
            ]
            if dock_orders:
                first = dock_orders[0]
                order_id = (
                    first.get("id")
                    or first.get("workOrderId")
                    or first.get("work_order_id")
                    or first.get("orderId")
                    or first.get("order_id")
                    or first.get("workOrderGuid")
                    or first.get("work_order_guid")
                )
                if order_id not in (None, ""):
                    return DirectActionResult(
                        action_id="inspection.fly_work_order",
                        params={
                            "ids": [order_id],
                            "workOrderNo": (
                                first.get("workOrderNo")
                                or first.get("work_order_no")
                                or first.get("orderNo")
                                or first.get("work_order_no")
                            ),
                            "finalSummary": result.get("finalSummary"),
                        },
                    )
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


def _is_dock_work_order(item: dict[str, Any]) -> bool:
    return work_order_group(item) == "covered"
