import json

from app.integrations.inspection.workflows import inspection_build_work_order_fill_state
from app.integrations.inspection.workflows import _merge_created_work_orders
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


def test_inspection_work_order_schema_requires_structured_model_arguments() -> None:
    schema = inspection_build_work_order_fill_state.args_schema.model_json_schema()

    assert schema["properties"]["plan"]["type"] == "object"
    coverage_schema = schema["properties"]["coverage_rows"]
    assert {item["type"] for item in coverage_schema["anyOf"]} == {"array", "null"}
    completed_schema = schema["properties"]["completed_groups"]
    assert {item["type"] for item in completed_schema["anyOf"]} == {"array", "null"}


def test_created_work_orders_deduplicate_by_business_number_before_internal_id() -> None:
    merged = _merge_created_work_orders(
        [{
            "id": "query-row-17",
            "work_order_no": "AL-20260805-003",
            "inspection_method": "drone",
        }],
        {
            "id": "357520855904816740",
            "work_order_no": "AL-20260805-003",
            "work_content": "10kV白路线无人机巡检，共9基杆塔",
        },
    )

    assert merged == [{
        "id": "357520855904816740",
        "work_order_no": "AL-20260805-003",
        "inspection_method": "drone",
        "work_content": "10kV白路线无人机巡检，共9基杆塔",
    }]


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

    completed = inspection_build_work_order_fill_state.invoke({
        "plan": plan,
        "coverage_rows": rows,
        "completed_groups": ["covered", "uncovered"],
        "created_work_orders": [
            {
                "id": "order-covered",
                "work_order_no": "AL-20260818-001",
                "work_content": "10kV白路线固定机场巡检，共1基杆塔",
                "inspection_method": "dock",
                "start_date": "2026-08-18T00:00:00",
                "end_date": "2026-08-18T23:59:59",
            },
            {
                "id": "order-uncovered",
                "work_order_no": "AL-20260818-002",
                "work_content": "10kV白路线无人机巡检，共1基杆塔",
                "inspection_method": "drone",
                "start_date": "2026-08-18T00:00:00",
                "end_date": "2026-08-18T23:59:59",
            },
        ],
    })

    assert completed["ok"] is True
    assert completed["workOrderFillState"]["status"] == "COMPLETED"
    assert completed["workOrderFillState"]["pendingWorkOrderGroups"] == []
    assert completed["workOrderFillState"]["executePayload"] is None
    assert completed["summary"] == "该计划的巡检工单已全部创建完成。"
    assert completed["finalSummary"] == (
        "已成功创建全部巡检工单，具体信息如下：\n\n"
        "### 工单 1｜固定机场工单\n"
        "- 工单编号：AL-20260818-001\n"
        "- 巡检内容：10kV白路线固定机场巡检，共1基杆塔\n"
        "- 巡检方式：固定机场\n"
        "- 起止时间：2026-08-18 00:00:00 至 2026-08-18 23:59:59\n\n"
        "### 工单 2｜无人机工单\n"
        "- 工单编号：AL-20260818-002\n"
        "- 巡检内容：10kV白路线无人机巡检，共1基杆塔\n"
        "- 巡检方式：无人机\n"
        "- 起止时间：2026-08-18 00:00:00 至 2026-08-18 23:59:59\n\n"
        "以上工单均属于临时计划“临时计划-白路线巡检”，已全部创建完成。"
    )
    direct = inspection_work_order_direct_action(completed)
    assert direct is not None
    assert direct.model_dump() == {
        "kind": "action",
        "action_id": "inspection.fly_work_order",
        "params": {
            "ids": ["order-covered"],
            "workOrderNo": "AL-20260818-001",
            "finalSummary": completed["finalSummary"],
        },
    }


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


def test_completed_drone_only_work_orders_do_not_offer_dock_takeoff() -> None:
    completed = inspection_build_work_order_fill_state.invoke({
        "plan": {
            "planGuid": "plan-1",
            "planName": "临时计划-线路巡检",
            "planType": "5",
            "inspectStartTime": "2026-08-18 00:00:00",
            "inspectEndTime": "2026-08-18 23:59:59",
        },
        "coverage_rows": [{
            "deviceGuid": "tower-1",
            "parentDeviceGuid": "line-1",
            "major": "dms",
        }],
        "completed_groups": ["uncovered"],
        "created_work_orders": [{
            "id": "order-1",
            "work_order_no": "AL-001",
            "inspection_method": "drone",
        }],
    })

    direct = inspection_work_order_direct_action(completed)

    assert direct is not None
    assert direct.model_dump()["kind"] == "message"


def test_completed_legacy_dock_record_offers_takeoff() -> None:
    result = {
        "ok": True,
        "workOrderFillState": {"status": "COMPLETED"},
        "finalSummary": "全部工单已创建完成。",
        "createdWorkOrders": [{
            "work_order_id": "order-dock",
            "work_order_no": "AL-DOCK-001",
            "inspection_method": "固定机场",
        }],
    }

    direct = inspection_work_order_direct_action(result)

    assert direct is not None
    assert direct.model_dump()["action_id"] == "inspection.fly_work_order"
    assert direct.model_dump()["params"]["ids"] == ["order-dock"]


def test_completed_split_work_orders_selects_legacy_airport_order_for_takeoff() -> None:
    result = {
        "ok": True,
        "workOrderFillState": {"status": "COMPLETED"},
        "finalSummary": "已成功创建全部巡检工单。",
        "createdWorkOrders": [
            {
                "work_order_id": "covered-order",
                "work_order_no": "AL-COVERED",
                "inspection_method": "fixed_airport_inspection",
            },
            {
                "work_order_id": "uncovered-order",
                "work_order_no": "AL-UNCOVERED",
                "inspection_method": "drone",
            },
        ],
    }

    direct = inspection_work_order_direct_action(result)

    assert direct is not None
    assert direct.model_dump() == {
        "kind": "action",
        "action_id": "inspection.fly_work_order",
        "params": {
            "ids": ["covered-order"],
            "workOrderNo": "AL-COVERED",
            "finalSummary": "已成功创建全部巡检工单。",
        },
    }
