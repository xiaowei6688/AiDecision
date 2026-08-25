"""Legacy-compatible inspection work-order summary rendering."""

from __future__ import annotations

from typing import Any

from app.integrations.inspection.workflow_shared import first_present


def merge_created_work_orders(
    created_work_orders: list[dict[str, Any]],
    current_work_order: dict[str, Any],
) -> list[dict[str, Any]]:
    """Merge query and receipt records by business number or internal ID."""

    merged: list[dict[str, Any] | None] = []
    aliases: dict[str, int] = {}
    for index, item in enumerate([*created_work_orders, current_work_order]):
        values = {name: value for name, value in item.items() if value not in (None, "")}
        item_aliases = work_order_aliases(values)
        matches = {aliases[value] for value in item_aliases if value in aliases}
        target = min(matches) if matches else len(merged)
        if target == len(merged):
            merged.append({})
        for duplicate in sorted(matches - {target}, reverse=True):
            duplicate_values = merged[duplicate]
            if duplicate_values is not None:
                merged[target] = {**duplicate_values, **(merged[target] or {})}
                merged[duplicate] = None
                for alias, position in list(aliases.items()):
                    if position == duplicate:
                        aliases[alias] = target
        merged[target] = {**(merged[target] or {}), **values}
        for alias in work_order_aliases(merged[target] or {}):
            aliases[alias] = target
        if not item_aliases:
            aliases[f"row-{index}"] = target
    return [item for item in merged if item is not None]


def work_order_aliases(item: dict[str, Any]) -> set[str]:
    return {
        str(value)
        for value in (
            first_present(item, "work_order_no", "workOrderNo", "orderNo"),
            first_present(item, "id", "workOrderId", "work_order_id"),
        )
        if value not in (None, "")
    }


def work_order_group(order: dict[str, Any]) -> str | None:
    """根据业务系统的巡检方式枚举判断工单所属的覆盖组。"""

    explicit_group = str(first_present(order, "group", "workOrderGroup") or "").strip().lower()
    if explicit_group in {"covered", "uncovered"}:
        return explicit_group

    value = str(
        first_present(
            order,
            "inspection_method",
            "inspectionMethod",
            "inspection_way",
            "inspectionWay",
            "work_order_type",
            "workOrderType",
        )
        or ""
    ).strip()
    normalized = value.lower()
    if (
        normalized in {"dock", "fixed_dock", "fixed_airport", "fixed_airport_inspection"}
        or any(marker in normalized for marker in ("airport", "dock"))
        or any(marker in value for marker in ("机场", "机巢"))
    ):
        return "covered"
    if (
        normalized == "drone"
        or "drone" in normalized
        or any(marker in value for marker in ("无人机", "飞手"))
    ):
        return "uncovered"
    return None


def work_order_final_summary(
    created_work_orders: list[dict[str, Any]],
    *,
    plan_name: str,
) -> str:
    lines = ["已成功创建全部巡检工单，具体信息如下："]
    for index, order in enumerate(created_work_orders, start=1):
        method = display_work_order_method(order)
        lines.extend([
            "",
            f"### 工单 {index}｜{method}工单",
            f"- 工单编号：{display_work_order_value(order, 'work_order_no', 'workOrderNo', 'orderNo')}",
            f"- 巡检内容：{display_work_order_value(order, 'work_content', 'workContent')}",
            f"- 巡检方式：{method}",
            "- 起止时间："
            f"{display_work_order_time(first_present(order, 'start_date', 'startDate'))} 至 "
            f"{display_work_order_time(first_present(order, 'end_date', 'endDate'))}",
        ])
    lines.extend([
        "",
        f"以上工单均属于临时计划“{plan_name}”，已全部创建完成。",
    ])
    return "\n".join(lines)


def display_work_order_method(order: dict[str, Any]) -> str:
    value = str(first_present(order, "inspection_method", "inspectionMethod") or "")
    if work_order_group(order) == "covered":
        return "固定机场"
    if work_order_group(order) == "uncovered":
        return "无人机"
    return value or "巡检"


def display_work_order_value(order: dict[str, Any], *keys: str) -> str:
    value = first_present(order, *keys)
    return str(value) if value not in (None, "") else "-"


def display_work_order_time(value: Any) -> str:
    if value in (None, ""):
        return "-"
    return str(value).replace("T", " ")
