"""Deterministic inspection continuations backed by real business queries."""

from __future__ import annotations

from typing import Any

from app.integrations.direct_results import DirectMessageResult, DirectResult
from app.integrations.inspection.direct_results import inspection_work_order_direct_action
from app.tools.broker import ToolBrokerRequest


_ALLOWED_TOOLS = (
    "inspection_query_plan_detail",
    "inspection_query_coverage",
    "inspection_query_work_order_detail",
    "inspection_query_work_order_resources",
    "inspection_build_work_order_fill_state",
)


async def inspection_continuation(
    continuation: dict[str, Any],
    context: Any,
) -> DirectResult | None:
    """Continue legacy inspection creation flows without allowing model summaries."""

    operation = str(continuation.get("operation") or "")
    if operation == "create_work_orders_from_plan":
        plan_id = str(continuation.get("planId") or "").strip()
        if not plan_id:
            return _failure("计划创建回执缺少计划 ID。")
        plan_result = await _run_tool(
            context,
            "inspection_query_plan_detail",
            {"plan_id": plan_id},
        )
        if isinstance(plan_result, DirectMessageResult):
            return plan_result
        plan = plan_result.get("plan")
        if not isinstance(plan, dict):
            return _failure("未能从业务系统获取新建计划的真实详情。")
        completed_groups: list[str] = []
        created_work_orders: list[dict[str, Any]] = []
    elif operation == "verify_work_order_and_continue":
        order_id = str(continuation.get("workOrderId") or "").strip()
        if not order_id:
            return _failure("工单创建回执缺少工单 ID。")
        verified = await _run_tool(
            context,
            "inspection_query_work_order_detail",
            {"order_id": order_id},
        )
        if isinstance(verified, DirectMessageResult):
            return verified
        plan = verified.get("plan")
        if not isinstance(plan, dict):
            return _failure("未能从业务系统获取已创建工单关联的计划详情。")
        completed_groups = [
            value for value in verified.get("completedGroups", [])
            if isinstance(value, str)
        ]
        created_work_orders = [
            value for value in verified.get("createdWorkOrders", [])
            if isinstance(value, dict)
        ]
    else:
        return None

    plan_guid = plan.get("planGuid") or plan.get("plan_guid")
    if not plan_guid:
        return _failure("真实计划详情缺少 planGuid，无法继续组装巡检工单。")
    coverage = await _run_tool(
        context,
        "inspection_query_coverage",
        {"plan_guid": str(plan_guid)},
    )
    if isinstance(coverage, DirectMessageResult):
        return coverage
    rows = coverage.get("rows")
    if not isinstance(rows, list):
        return _failure("未能从业务系统获取计划对应的杆塔覆盖数据。")

    fill = await _run_tool(
        context,
        "inspection_build_work_order_fill_state",
        {
            "plan": plan,
            "coverage_rows": rows,
            "completed_groups": completed_groups,
            "created_work_orders": created_work_orders,
        },
    )
    if isinstance(fill, DirectMessageResult):
        return fill
    fill = _with_created_work_orders(fill, created_work_orders)
    direct = inspection_work_order_direct_action(fill)
    if direct is not None:
        return direct

    state = fill.get("workOrderFillState") if isinstance(fill, dict) else None
    missing_fields = set(state.get("missingFields") or []) if isinstance(state, dict) else set()
    needs_resources = (
        isinstance(state, dict)
        and state.get("status") == "NEED_MORE_INFO"
        and state.get("currentWorkOrderGroup") == "uncovered"
        and bool(missing_fields)
        and missing_fields <= {"equipSn", "flightWorkers"}
    )
    if not needs_resources:
        return _failure(_next_question(fill))

    resources = await _run_tool(context, "inspection_query_work_order_resources", {})
    if isinstance(resources, DirectMessageResult):
        return resources
    fill = await _run_tool(
        context,
        "inspection_build_work_order_fill_state",
        {
            "plan": plan,
            "coverage_rows": rows,
            "completed_groups": completed_groups,
            "created_work_orders": created_work_orders,
            "equip_sn": resources.get("suggestedEquipSn"),
            "flight_workers": resources.get("suggestedFlightWorkers"),
        },
    )
    if isinstance(fill, DirectMessageResult):
        return fill
    fill = _with_created_work_orders(fill, created_work_orders)
    direct = inspection_work_order_direct_action(fill)
    return direct if direct is not None else _failure(_next_question(fill))


async def _run_tool(
    context: Any,
    tool_name: str,
    arguments: dict[str, Any],
) -> dict[str, Any] | DirectMessageResult:
    result = await context.tool_broker.execute(
        ToolBrokerRequest(
            business_id="inspection",
            tool_name=tool_name,
            arguments=arguments,
        ),
        _ALLOWED_TOOLS,
    )
    value = result.result
    if result.audit.status != "success" or not isinstance(value, dict) or value.get("ok") is False:
        detail = value.get("error") if isinstance(value, dict) else None
        return _failure(str(detail or "巡检业务数据查询失败。"))
    return value


def _next_question(value: Any) -> str:
    if isinstance(value, dict):
        state = value.get("workOrderFillState")
        if isinstance(state, dict) and isinstance(state.get("nextQuestion"), str):
            return state["nextQuestion"]
    return "巡检工单数据尚未准备完成。"


def _with_created_work_orders(
    fill: dict[str, Any],
    created_work_orders: list[dict[str, Any]],
) -> dict[str, Any]:
    state = fill.get("workOrderFillState")
    if (
        isinstance(state, dict)
        and state.get("status") == "COMPLETED"
        and created_work_orders
    ):
        # 最终起飞确认使用查询到的真实工单，不能只依赖总结文本。
        return {**fill, "createdWorkOrders": created_work_orders}
    return fill


def _failure(message: str) -> DirectMessageResult:
    return DirectMessageResult(
        message=message,
        data={"businessId": "inspection"},
        status="failed",
    )
