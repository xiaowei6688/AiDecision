import json

from app.integrations.inspection.workflows import inspection_build_work_order_fill_state
from app.integrations.inspection.direct_results import inspection_work_order_direct_action


def test_inspection_work_order_workflow_preserves_legacy_fill_state() -> None:
    result = inspection_build_work_order_fill_state.invoke({
        "plan": {
            "planGuid": "plan-1",
            "planName": "临时计划-线路巡检",
            "planType": "5",
            "inspectStartTime": "2026-08-14 08:00:00",
            "inspectEndTime": "2026-08-14 10:00:00",
        },
        "coverage_rows": [{
            "line_uid": "line-1",
            "tower_uid": "tower-1",
            "tower_name": "杆塔1",
            "airport_uid": "dock-1",
        }],
    })

    state = result["workOrderFillState"]
    assert result["ok"] is True
    assert state["actionCode"] == "createTempOrder"
    assert state["routePath"] == "/workOrder/review"
    assert state["executePayload"]["inspectionMethod"] == "dock"
    assert state["pendingWorkOrderGroups"] == ["covered"]
    direct = inspection_work_order_direct_action(result)
    assert direct is not None
    assert direct.action_id == "inspection.create_work_order"
    assert direct.params == state["executePayload"]


def test_inspection_work_order_accepts_stringified_model_arguments() -> None:
    plan = {
        "planGuid": "plan-1",
        "planType": "5",
        "inspectStartTime": "2026-08-18 00:00:00",
        "inspectEndTime": "2026-08-18 23:59:59",
    }
    rows = [{
        "tower_guid": "tower-1",
        "basic_tower_ledger_name": "10kV白路线#1",
        "line_guid": "line-1",
        "basic_line_ledger_name": "10kV白路线",
        "major": "dms",
        "dockGuid": "dock-1",
    }]

    result = inspection_build_work_order_fill_state.invoke({
        "plan": json.dumps(plan, ensure_ascii=False),
        "coverage_rows": json.dumps(rows, ensure_ascii=False),
        "group": "covered",
    })

    detail = result["workOrderFillState"]["executePayload"]["orderDetailList"][0]
    assert result["ok"] is True
    assert detail["deviceGuid"] == "tower-1"
    assert detail["parentDeviceGuid"] == "line-1"
    assert detail["workNature"] == "fine_inspect_dms"


def test_inspection_work_order_accepts_backslash_escaped_model_arguments() -> None:
    plan = {
        "planGuid": "plan-1",
        "planType": "3",
        "inspectStartTime": "2026-07-27 00:00:00",
        "inspectEndTime": "2026-08-02 23:59:59",
    }
    rows = [{
        "deviceGuid": "tower-1",
        "deviceName": "10kV白路线#1",
        "parentDeviceGuid": "line-1",
        "parentDeviceName": "10kV白路线",
        "major": "dms",
        "dockGuid": "dock-1",
    }]
    escaped_plan = json.dumps(plan, ensure_ascii=False).replace('"', '\\"')
    escaped_rows = json.dumps(rows, ensure_ascii=False).replace('"', '\\"')

    result = inspection_build_work_order_fill_state.invoke({
        "plan": escaped_plan,
        "coverage_rows": escaped_rows,
        "group": "covered",
    })

    assert result["ok"] is True
    assert result["workOrderFillState"]["status"] == "READY"
    assert len(
        result["workOrderFillState"]["executePayload"]["orderDetailList"]
    ) == 1


def test_inspection_work_orders_are_split_and_advanced_one_group_at_a_time() -> None:
    plan = {
        "planGuid": "plan-1",
        "planName": "临时计划-白路线巡检",
        "planType": "5",
        "inspectStartTime": "2026-08-18 00:00:00",
        "inspectEndTime": "2026-08-18 23:59:59",
    }
    rows = [
        {
            "line_uid": "line-1",
            "line_name": "10kV白路线",
            "tower_uid": "tower-1",
            "tower_name": "1号杆塔",
            "major": "dms",
            "airport_uid": "dock-1",
        },
        {
            "line_uid": "line-1",
            "line_name": "10kV白路线",
            "tower_uid": "tower-2",
            "tower_name": "2号杆塔",
            "major": "dms",
        },
    ]

    first = inspection_build_work_order_fill_state.invoke({
        "plan": plan,
        "coverage_rows": rows,
    })["workOrderFillState"]

    assert first["status"] == "READY"
    assert first["currentWorkOrderGroup"] == "covered"
    assert first["pendingWorkOrderGroups"] == ["covered", "uncovered"]
    assert first["remainingWorkOrderGroups"] == ["uncovered"]
    assert first["executePayload"]["inspectionMethod"] == "dock"
    assert first["executePayload"]["priority"] == 1
    assert first["executePayload"]["workNature"] == "fine_inspect_dms"
    assert [item["deviceGuid"] for item in first["executePayload"]["orderDetailList"]] == ["tower-1"]

    second = inspection_build_work_order_fill_state.invoke({
        "plan": plan,
        "coverage_rows": rows,
        "completed_groups": ["covered"],
        "equip_sn": "drone-1",
        "flight_workers": ["worker-1"],
    })["workOrderFillState"]

    assert second["status"] == "READY"
    assert second["currentWorkOrderGroup"] == "uncovered"
    assert second["pendingWorkOrderGroups"] == ["uncovered"]
    assert second["executePayload"]["inspectionMethod"] == "drone"
    assert second["executePayload"]["equipSn"] == "drone-1"
    assert second["executePayload"]["flightWorkers"] == ["worker-1"]
    assert [item["deviceGuid"] for item in second["executePayload"]["orderDetailList"]] == ["tower-2"]


def test_inspection_uncovered_work_order_requires_real_resources() -> None:
    result = inspection_build_work_order_fill_state.invoke({
        "plan": {
            "planGuid": "plan-1",
            "planType": "5",
            "inspectStartTime": "2026-08-18 00:00:00",
            "inspectEndTime": "2026-08-18 23:59:59",
        },
        "coverage_rows": [{
            "line_uid": "line-1",
            "tower_uid": "tower-1",
            "tower_name": "1号杆塔",
            "major": "dms",
        }],
    })

    state = result["workOrderFillState"]
    assert result["ok"] is False
    assert state["status"] == "NEED_MORE_INFO"
    assert state["missingFields"] == ["equipSn", "flightWorkers"]
    assert state["executePayload"] is None
