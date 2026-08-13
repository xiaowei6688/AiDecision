from app.integrations.inspection.workflows import inspection_build_work_order_fill_state


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
