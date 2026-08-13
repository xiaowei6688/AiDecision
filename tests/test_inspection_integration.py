import pytest

from app.actions.policy import PolicyEngine
from app.actions.schemas import ActionExecutionContext
from app.integrations.inspection.actions import CREATE_PLAN, CREATE_WORK_ORDER
from app.integrations.inspection.notifications import (
    InspectionNotificationRequest,
    build_notification_event,
)
from app.integrations.inspection.checks import valid_time_window
from app.integrations.inspection.models import CreateInspectionWorkOrderInput
from app.integrations.inspection.ui import inspection_action_result_projection
from app.actions.schemas import ActionResult
from app.integrations.projections import register_action_result_projection, project_action_result


def test_inspection_actions_are_confirmed_writes() -> None:
    assert CREATE_PLAN.confirmation.required
    assert CREATE_WORK_ORDER.confirmation.required
    assert CREATE_WORK_ORDER.executor.adapter == "inspection"


def test_inspection_work_order_requires_a_drone_for_drone_method() -> None:
    with pytest.raises(ValueError, match="equipSn"):
        CreateInspectionWorkOrderInput.model_validate({
            "planGuid": "plan-1",
            "priority": 1,
            "major": "tms",
            "workNature": "fine_inspect_tms",
            "isCycle": "0",
            "inspectionMethod": "drone",
            "startDate": "2026-08-14 08:00:00",
            "endDate": "2026-08-14 10:00:00",
            "orderDetailList": [{"deviceGuid": "tower-1"}],
            "workContent": "线路巡检",
        })


def test_inspection_time_window_rejects_reversed_times() -> None:
    assert valid_time_window(
        CREATE_PLAN,
        {"inspectStartTime": "2026-08-14 10:00:00", "inspectEndTime": "2026-08-14 08:00:00"},
        ActionExecutionContext(),
    ) == "结束时间必须晚于开始时间"


def test_policy_accepts_a_valid_inspection_time_window() -> None:
    policy = PolicyEngine()
    policy.register_pre_check("inspection.valid_time_window", valid_time_window)

    result = policy.evaluate(CREATE_PLAN, {
        "inspectStartTime": "2026-08-14 08:00:00",
        "inspectEndTime": "2026-08-14 10:00:00",
    }, ActionExecutionContext())

    assert result.allowed


def test_inspection_confirmation_projection_is_integration_owned() -> None:
    result = ActionResult(
        status="requires_confirmation",
        action_id="inspection.create_work_order",
        message="confirm",
        data={"action": {"title": "创建巡检工单"}, "params": {"planGuid": "plan-1"}},
    )

    register_action_result_projection(inspection_action_result_projection)
    assert inspection_action_result_projection(result)["actionCode"] == "createTempOrder"
    assert project_action_result(result)["executeApi"] == "/order/createTempOrder"


def test_inspection_notification_builds_legacy_event_payload() -> None:
    request = InspectionNotificationRequest.model_validate(
        {
            "type": "startFlying",
            "content": {
                "workOrderId": 123,
                "workOrderNo": "GD20250101",
                "dockSn": "dock-1",
                "droneSn": "drone-1",
            },
        }
    )

    event = build_notification_event(request)

    assert event["type"] == "human_action_required"
    assert event["data"]["interrupts"][0]["actionCode"] == "flightMonitoring"
