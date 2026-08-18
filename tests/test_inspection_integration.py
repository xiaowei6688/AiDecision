from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.actions.policy import PolicyEngine
from app.actions.schemas import ActionExecutionContext
from app.integrations.inspection.actions import CREATE_PLAN, CREATE_WORK_ORDER
from app.integrations.inspection.allcore_auth import InspectionAllCoreAuthClient
from app.integrations.inspection.notifications import (
    InspectionNotificationRequest,
    build_notification_event,
)
from app.integrations.inspection.checks import valid_time_window
from app.integrations.inspection.models import CreateInspectionPlanInput, CreateInspectionWorkOrderInput
from app.core.runtime_context import RequestRuntimeContext, reset_runtime_context, set_runtime_context
from app.integrations.inspection.adapter import InspectionAdapter
from app.integrations.inspection.config import InspectionSettings
from app.integrations.inspection.ui import (
    inspection_action_result_projection,
    inspection_frontend_callback_resume_projection,
    inspection_human_interrupt_projection,
)
from app.integrations.inspection.workflows import (
    inspection_build_plan_fill_state,
    inspection_query_coverage,
    inspection_query_device_data,
    inspection_query_plan_detail,
    inspection_query_work_order_detail,
    inspection_query_work_order_resources,
)
from app.integrations.inspection.websocket_actions import inspection_action_result_to_resume
from app.integrations.inspection.continuations import inspection_continuation
from app.integrations.inspection.workflows import inspection_build_work_order_fill_state
from app.schemas.chat import WebSocketClientEvent
from app.actions.schemas import ActionResult
from app.integrations.projections import ProjectionRegistry


def test_inspection_actions_are_confirmed_writes() -> None:
    assert CREATE_PLAN.confirmation.required
    assert CREATE_WORK_ORDER.confirmation.required
    assert CREATE_WORK_ORDER.executor.adapter == "inspection"
    assert CREATE_PLAN.pre_checks == ["inspection.valid_time_window"]
    assert CREATE_WORK_ORDER.pre_checks == []


def test_inspection_registers_user_friendly_tool_steps() -> None:
    from app.integrations.context import PluginContext
    from app.integrations.inspection.registration import register_inspection_tools

    context = PluginContext()
    register_inspection_tools(context)

    step = context.tools.step("inspection_query_device_data")
    assert step.title == "核对线路杆塔台账"
    assert step.summary == "正在按线路和范围核对杆塔 UID、名称、专业及所属线路"


@pytest.mark.asyncio
async def test_inspection_work_order_continuation_uses_real_records_for_final_summary() -> None:
    plan = {
        "planGuid": "plan-1",
        "planName": "临时计划-白路线巡检",
        "planType": "5",
        "inspectStartTime": "2026-08-18 00:00:00",
        "inspectEndTime": "2026-08-18 23:59:59",
    }
    created = [
        {
            "id": "order-1",
            "work_order_no": "AL-20260818-001",
            "work_content": "固定机场巡检，共1基杆塔",
            "inspection_method": "dock",
            "start_date": "2026-08-18 00:00:00",
            "end_date": "2026-08-18 23:59:59",
        },
        {
            "id": "order-2",
            "work_order_no": "AL-20260818-002",
            "work_content": "无人机巡检，共1基杆塔",
            "inspection_method": "drone",
            "start_date": "2026-08-18 00:00:00",
            "end_date": "2026-08-18 23:59:59",
        },
    ]
    rows = [
        {
            "deviceGuid": "tower-1",
            "deviceName": "10kV白路线#1",
            "parentDeviceGuid": "line-1",
            "parentDeviceName": "10kV白路线",
            "major": "dms",
            "dockGuid": "dock-1",
        },
        {
            "deviceGuid": "tower-2",
            "deviceName": "10kV白路线#2",
            "parentDeviceGuid": "line-1",
            "parentDeviceName": "10kV白路线",
            "major": "dms",
        },
    ]
    calls: list[str] = []

    class Broker:
        async def execute(self, request, _allowed):
            calls.append(request.tool_name)
            if request.tool_name == "inspection_query_work_order_detail":
                result = {
                    "ok": True,
                    "plan": plan,
                    "completedGroups": ["covered", "uncovered"],
                    "createdWorkOrders": created,
                }
            elif request.tool_name == "inspection_query_coverage":
                result = {"ok": True, "rows": rows}
            elif request.tool_name == "inspection_build_work_order_fill_state":
                result = inspection_build_work_order_fill_state.invoke(request.arguments)
            else:
                raise AssertionError(f"unexpected tool: {request.tool_name}")
            return SimpleNamespace(result=result, audit=SimpleNamespace(status="success"))

    direct = await inspection_continuation(
        {
            "businessId": "inspection",
            "operation": "verify_work_order_and_continue",
            "workOrderId": "order-2",
        },
        SimpleNamespace(tool_broker=Broker()),
    )

    assert direct is not None
    assert direct.model_dump()["kind"] == "message"
    assert "AL-20260818-001" in direct.model_dump()["message"]
    assert "AL-20260818-002" in direct.model_dump()["message"]
    assert calls == [
        "inspection_query_work_order_detail",
        "inspection_query_coverage",
        "inspection_build_work_order_fill_state",
    ]


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


def test_inspection_plan_objects_are_normalized_for_legacy_payload() -> None:
    payload = CreateInspectionPlanInput.model_validate({
        "planType": "5",
        "planName": "临时巡检计划",
        "inspectStartTime": "2026-08-14 08:00:00",
        "inspectEndTime": "2026-08-14 10:00:00",
        "planObjectList": [{
            "tower_guid": "tower-1",
            "basic_tower_ledger_name": "杆塔1",
            "major": "tms",
            "line_guid": "line-1",
            "basic_line_ledger_name": "线路1",
        }],
    }).model_dump(mode="json")

    assert payload["plan_object_list"] == [{
        "deviceGuid": "tower-1",
        "deviceName": "杆塔1",
        "major": "tms",
        "parentDeviceGuid": "line-1",
        "parentDeviceName": "线路1",
    }]


def test_inspection_plan_fields_follow_legacy_type_and_name_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.integrations.inspection.models.time.time", lambda: 1787000000)

    payload = CreateInspectionPlanInput.model_validate({
        "planType": "临时计划",
        "planName": "10kV十九线#1-6 临时巡检计划",
        "inspectStartTime": "2026-08-18 08:00:00",
        "inspectEndTime": "2026-08-18 10:00:00",
        "planObjectList": [{
            "deviceGuid": "tower-1",
            "deviceName": "10kV十九线#1",
            "major": "dms",
            "parentDeviceGuid": "line-1",
            "parentDeviceName": "10kV十九线",
        }],
    }).model_dump(mode="json")

    assert payload["plan_type"] == "5"
    assert payload["plan_name"] == "临时计划-2026-08-18-10kV十九线巡检-1787000000"


@pytest.mark.parametrize("plan_type", ["临时巡检", "临时巡检计划"])
def test_inspection_plan_accepts_temporary_inspection_type_aliases(
    monkeypatch: pytest.MonkeyPatch,
    plan_type: str,
) -> None:
    monkeypatch.setattr("app.integrations.inspection.models.time.time", lambda: 1787000000)

    result = inspection_build_plan_fill_state.invoke({
        "plan_type": plan_type,
        "inspect_start_time": "2026-08-18 08:00:00",
        "inspect_end_time": "2026-08-18 10:00:00",
        "plan_object_list": [{
            "deviceGuid": "tower-1",
            "deviceName": "10kV白路线#1",
            "major": "dms",
            "parentDeviceGuid": "line-1",
            "parentDeviceName": "10kV白路线",
        }],
    })

    assert result["ok"] is True
    assert result["executePayload"]["planType"] == "5"
    assert result["displayFields"]["planType"] == "临时计划"


def test_inspection_plan_fill_state_directly_routes_large_payload_to_action() -> None:
    result = inspection_build_plan_fill_state.invoke({
        "plan_type": "5",
        "inspect_start_time": "2026-08-18 08:00:00",
        "inspect_end_time": "2026-08-18 10:00:00",
        "plan_object_list": [{
            "deviceGuid": "tower-1",
            "deviceName": "10kV白路线#1",
            "major": "dms",
            "parentDeviceGuid": "line-1",
            "parentDeviceName": "10kV白路线",
        }],
    })

    assert result["_framework"]["direct_action"] == {
        "action_id": "inspection.create_plan",
        "params": result["executePayload"],
    }


def test_inspection_plan_fill_state_is_stable_when_action_validates_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.integrations.inspection.models.time.time", lambda: 1787000000)
    result = inspection_build_plan_fill_state.invoke({
        "plan_type": "临时计划",
        "inspect_start_time": "2026-08-18 08:00:00",
        "inspect_end_time": "2026-08-18 10:00:00",
        "plan_object_list": [{
            "deviceGuid": "tower-1",
            "deviceName": "10kV十九线#1",
            "major": "dms",
            "parentDeviceGuid": "line-1",
            "parentDeviceName": "10kV十九线",
        }],
    })
    generated_name = result["executePayload"]["planName"]

    monkeypatch.setattr("app.integrations.inspection.models.time.time", lambda: 1787000999)
    validated = CreateInspectionPlanInput.model_validate(
        result["executePayload"]
    ).model_dump(mode="json", by_alias=True)

    assert result["ok"] is True
    assert result["executePayload"]["planType"] == "5"
    assert generated_name == "临时计划-2026-08-18-10kV十九线巡检-1787000000"
    assert validated["planName"] == generated_name


def test_inspection_plan_uses_relative_date_instead_of_model_guessed_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.tools.datetime_tool._now",
        lambda tz: datetime(2026, 8, 17, 10, 0, 0, tzinfo=tz),
    )
    monkeypatch.setattr("app.integrations.inspection.models.time.time", lambda: 1787000000)

    result = inspection_build_plan_fill_state.invoke({
        "plan_type": "临时计划",
        "time_expression": "明天的临时巡检，10kV白路线的1到4号杆塔",
        "inspect_start_time": "2024-12-20 08:00:00",
        "inspect_end_time": "2024-12-20 18:00:00",
        "plan_object_list": [{
            "deviceGuid": "tower-1",
            "deviceName": "10kV白路线#1",
            "major": "dms",
            "parentDeviceGuid": "line-1",
            "parentDeviceName": "10kV白路线",
        }],
    })

    assert result["ok"] is True
    assert result["executePayload"]["inspectStartTime"] == "2026-08-18 00:00:00"
    assert result["executePayload"]["inspectEndTime"] == "2026-08-18 23:59:59"
    assert result["executePayload"]["planName"] == (
        "临时计划-2026-08-18-10kV白路线巡检-1787000000"
    )


def test_inspection_plan_rejects_historical_absolute_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.tools.datetime_tool._now",
        lambda tz: datetime(2026, 8, 17, 10, 0, 0, tzinfo=tz),
    )

    result = inspection_build_plan_fill_state.invoke({
        "plan_type": "临时计划",
        "inspect_start_time": "2024-12-20 08:00:00",
        "inspect_end_time": "2024-12-20 18:00:00",
        "plan_object_list": [{
            "deviceGuid": "tower-1",
            "deviceName": "10kV白路线#1",
            "major": "dms",
            "parentDeviceGuid": "line-1",
            "parentDeviceName": "10kV白路线",
        }],
    })

    assert result["ok"] is False
    assert result["errorCode"] == "expired_inspection_date"


def test_inspection_plan_object_old_fields_override_blank_legacy_keys() -> None:
    payload = CreateInspectionPlanInput.model_validate({
        "planType": "5",
        "planName": "临时巡检计划",
        "inspectStartTime": "2026-08-14 08:00:00",
        "inspectEndTime": "2026-08-14 10:00:00",
        "planObjectList": [{
            "deviceGuid": None,
            "deviceName": None,
            "major": "tms",
            "parentDeviceGuid": None,
            "parentDeviceName": None,
            "tower_guid": "tower-1",
            "basic_tower_ledger_name": "杆塔1",
            "line_guid": "line-1",
            "basic_line_ledger_name": "线路1",
        }],
    }).model_dump(mode="json")

    assert payload["plan_object_list"] == [{
        "deviceGuid": "tower-1",
        "deviceName": "杆塔1",
        "major": "tms",
        "parentDeviceGuid": "line-1",
        "parentDeviceName": "线路1",
    }]


def test_inspection_plan_object_rejects_blank_required_object_fields() -> None:
    with pytest.raises(ValueError, match="planObjectList\\[0\\] 缺少真实巡检对象字段"):
        CreateInspectionPlanInput.model_validate({
            "planType": "5",
            "planName": "临时巡检计划",
            "inspectStartTime": "2026-08-14 08:00:00",
            "inspectEndTime": "2026-08-14 10:00:00",
            "planObjectList": [{
                "deviceGuid": None,
                "deviceName": None,
                "major": None,
                "parentDeviceGuid": None,
                "parentDeviceName": None,
            }],
        })


def test_inspection_plan_object_rejects_guessed_name_values() -> None:
    with pytest.raises(ValueError, match="疑似使用名称冒充 GUID"):
        CreateInspectionPlanInput.model_validate({
            "planType": "5",
            "planName": "临时巡检计划",
            "inspectStartTime": "2026-08-14 08:00:00",
            "inspectEndTime": "2026-08-14 10:00:00",
            "planObjectList": [{
                "deviceGuid": "10kV十九线#3",
                "deviceName": "10kV十九线#3",
                "major": "10kV十九线",
                "parentDeviceGuid": "10kV十九线",
                "parentDeviceName": "10kV十九线",
            }],
        })


def test_inspection_time_window_rejects_reversed_times() -> None:
    assert valid_time_window(
        CREATE_PLAN,
        {"inspectStartTime": "2026-08-14 10:00:00", "inspectEndTime": "2026-08-14 08:00:00"},
        ActionExecutionContext(),
    ) == "结束时间必须晚于开始时间"


def test_inspection_time_window_rejects_historical_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.integrations.inspection.checks._today",
        lambda timezone: datetime(2026, 8, 17, tzinfo=ZoneInfo(timezone)),
    )

    assert valid_time_window(
        CREATE_PLAN,
        {"inspectStartTime": "2024-12-20 08:00:00", "inspectEndTime": "2024-12-20 18:00:00"},
        ActionExecutionContext(),
    ) == "巡检开始日期不能早于今天"


def test_policy_accepts_a_valid_inspection_time_window() -> None:
    policy = PolicyEngine()
    policy.register_pre_check("inspection.valid_time_window", valid_time_window)

    result = policy.evaluate(CREATE_PLAN, {
        "inspectStartTime": "2099-08-14 08:00:00",
        "inspectEndTime": "2099-08-14 10:00:00",
    }, ActionExecutionContext())

    assert result.allowed


def test_existing_inspection_plan_can_create_work_order_after_plan_window() -> None:
    policy = PolicyEngine()
    policy.register_pre_check("inspection.valid_time_window", valid_time_window)

    result = policy.evaluate(CREATE_WORK_ORDER, {
        "startDate": "2026-07-27 00:00:00",
        "endDate": "2026-08-02 23:59:59",
    }, ActionExecutionContext())

    assert result.allowed


def test_inspection_confirmation_projection_is_integration_owned() -> None:
    result = ActionResult(
        status="requires_confirmation",
        action_id="inspection.create_work_order",
        message="confirm",
        data={"action": {"title": "创建巡检工单"}, "params": {"planGuid": "plan-1"}},
    )

    projections = ProjectionRegistry()
    projections.register_action_result(inspection_action_result_projection)
    assert inspection_action_result_projection(result)["actionCode"] == "createTempOrder"
    assert projections.project_action_result(result)["executeApi"] == "/order/createTempOrder"


def test_inspection_create_plan_projection_uses_legacy_plan_object_shape() -> None:
    result = ActionResult(
        status="requires_confirmation",
        action_id="inspection.create_plan",
        message="confirm",
        data={
            "action": {"title": "创建巡检计划"},
            "confirmation_token": "token-1",
            "params": {
                "plan_type": "5",
                "plan_name": "临时巡检计划",
                "inspect_start_time": "2026-08-14 08:00:00",
                "inspect_end_time": "2026-08-14 10:00:00",
                "plan_object_list": [{
                    "deviceGuid": "tower-1",
                    "deviceName": "杆塔1",
                    "major": "tms",
                    "parentDeviceGuid": "line-1",
                    "parentDeviceName": "线路1",
                }],
            },
        },
    )

    projected = inspection_action_result_projection(result)

    assert projected["actionCode"] == "createPlan"
    assert projected["executePayload"]["planType"] == "5"
    assert projected["executePayload"]["planObjectList"] == [{
        "deviceGuid": "tower-1",
        "deviceName": "杆塔1",
        "major": "tms",
        "parentDeviceGuid": "line-1",
        "parentDeviceName": "线路1",
    }]
    assert projected["confirmation_token"] == "token-1"


def test_inspection_human_interrupt_projection_flattens_legacy_payload() -> None:
    interrupt = {
        "question": "请确认是否创建以下巡检工单",
        "allowed_actions": ["approve", "reject", "edit"],
        "recommended_action": "approve",
        "ui_type": "confirmation",
        "payload": {
            "businessId": "inspection",
            "actionCode": "createTempOrder",
            "executeApi": "/order/createTempOrder",
            "executePayload": {"planGuid": "plan-1"},
            "confirmation_token": "token-1",
        },
    }

    projections = ProjectionRegistry()
    projections.register_human_interrupt(inspection_human_interrupt_projection)
    projected = projections.project_human_interrupt([interrupt])

    assert projected["content"] == "请确认是否创建以下巡检工单"
    assert projected["data"]["businessId"] == "inspection"
    assert projected["data"]["actionCode"] == "createTempOrder"
    assert projected["data"]["executeApi"] == "/order/createTempOrder"
    assert projected["data"]["interrupts"][0]["confirmation_token"] == "token-1"


def test_inspection_plan_frontend_callback_finishes_plan_flow_only() -> None:
    projected = inspection_frontend_callback_resume_projection(
        {
            "status": "requires_confirmation",
            "action_id": "inspection.create_plan",
            "actionCode": "createPlan",
            "executePayload": {"planName": "临时计划"},
        },
        {
            "action": "approve",
            "content": "计划已创建",
            "data": {
                "success": True,
                "actionCode": "createPlan",
                "planId": "plan-1",
            },
        },
    )

    assert projected["status"] == "success"
    assert projected["message"] == "计划已创建"
    assert projected["data"]["createdPlanId"] == "plan-1"
    assert projected["data"]["final"] is False
    assert projected["data"]["businessContinuation"]["planId"] == "plan-1"
    assert "拆分巡检工单" in projected["data"]["nextUserAction"]


def test_legacy_create_plan_action_result_finishes_with_created_plan_id() -> None:
    request = inspection_action_result_to_resume(WebSocketClientEvent.model_validate({
        "type": "actionResult",
        "session_id": "session-1",
        "action_result": {
            "action_code": "createPlan",
            "content": None,
            "data": {
                "code": 200,
                "success": True,
                "data": "357520855904816740",
                "msg": "操作成功",
            },
        },
    }))
    assert request is not None

    projected = inspection_frontend_callback_resume_projection(
        {
            "status": "requires_confirmation",
            "action_id": "inspection.create_plan",
            "actionCode": "createPlan",
            "executePayload": {"planName": "临时计划"},
        },
        request.model_dump(),
    )

    assert projected["status"] == "success"
    assert projected["message"] == "操作成功"
    assert projected["data"]["createdPlanId"] == "357520855904816740"
    assert projected["data"]["final"] is False
    assert projected["data"]["businessContinuation"] == {
        "businessId": "inspection",
        "operation": "create_work_orders_from_plan",
        "planId": "357520855904816740",
    }


def test_inspection_plan_plain_resume_does_not_fake_action_result() -> None:
    projected = inspection_frontend_callback_resume_projection(
        {
            "action_id": "inspection.create_plan",
            "actionCode": "createPlan",
        },
        {"action": "approve", "content": "确认", "data": {}},
    )

    assert projected["status"] == "failed"
    assert projected["error_code"] == "ACTION_RESULT_REQUIRED"


def test_inspection_work_order_approve_waits_for_action_result() -> None:
    projected = inspection_frontend_callback_resume_projection(
        {
            "status": "requires_confirmation",
            "action_id": "inspection.create_work_order",
            "actionCode": "createTempOrder",
            "executePayload": {"planGuid": "plan-1", "inspectionMethod": "dock"},
        },
        {
            "action": "approve",
            "content": "确认执行此操作",
            "data": {},
        },
    )

    assert projected["status"] == "updated"
    assert projected["data"]["awaitingActionResult"] is True
    assert projected["data"]["final"] is False
    assert "actionResult" in projected["message"]


def test_inspection_work_order_rejects_wrong_action_result_code() -> None:
    projected = inspection_frontend_callback_resume_projection(
        {
            "action_id": "inspection.create_work_order",
            "actionCode": "createTempOrder",
        },
        {
            "action": "approve",
            "data": {"actionCode": "createPlan"},
        },
    )

    assert projected["status"] == "failed"
    assert projected["error_code"] == "ACTION_RESULT_REQUIRED"


def test_inspection_work_order_action_result_requires_post_create_verification() -> None:
    request = inspection_action_result_to_resume(WebSocketClientEvent.model_validate({
        "type": "actionResult",
        "session_id": "session-1",
        "action_result": {
            "action_code": "createTempOrder",
            "data": {"code": 200, "data": "order-1", "msg": "操作成功"},
        },
    }))
    assert request is not None

    projected = inspection_frontend_callback_resume_projection(
        {
            "action_id": "inspection.create_work_order",
            "executePayload": {"inspectionMethod": "dock"},
        },
        request.model_dump(),
    )

    assert projected["status"] == "success"
    assert projected["data"]["createdWorkOrderId"] == "order-1"
    assert projected["data"]["completedWorkOrderGroup"] == "covered"
    assert projected["data"]["final"] is False
    assert "校验" in projected["data"]["nextUserAction"]


def test_inspection_queries_drone_and_worker_resources_from_plugin_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self._payload = payload
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return self._payload

    calls: list[tuple[str, str, object, object]] = []

    def get(url: str, **kwargs: object) -> Response:
        calls.append(("GET", url, kwargs.get("json"), kwargs.get("headers")))
        return Response({"data": {"records": [{"equipSn": "drone-1"}]}})

    def post(url: str, **kwargs: object) -> Response:
        calls.append(("POST", url, kwargs.get("json"), kwargs.get("headers")))
        return Response({"data": {"records": [{"id": "worker-1"}]}})

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_settings",
        lambda: InspectionSettings(
            _env_file=None,
            api_base_url="http://inspection.local",
            drone_list_url=None,
            flight_worker_list_url=None,
            api_timeout_seconds=30,
            allcore_auth_token="resource-token",
        ),
    )
    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_allcore_auth_client",
        lambda: InspectionAllCoreAuthClient(
            InspectionSettings(_env_file=None, allcore_auth_token="resource-token")
        ),
    )
    monkeypatch.setattr("httpx.get", get)
    monkeypatch.setattr("httpx.post", post)

    result = inspection_query_work_order_resources.invoke({})

    assert result["ok"] is True
    assert result["suggestedEquipSn"] == "drone-1"
    assert result["suggestedFlightWorkers"] == ["worker-1"]
    assert calls == [
        (
            "GET",
            "http://inspection.local/api/main-server/equip/drone/list",
            None,
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "allcore-auth": "bearer resource-token",
            },
        ),
        (
            "POST",
            "http://inspection.local/api/main-server/person/fieldWorkInfo/getList",
            {"deviceType": ""},
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "allcore-auth": "bearer resource-token",
            },
        ),
    ]


def test_inspection_plan_detail_uses_plugin_owned_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"code": 200, "data": {"planGuid": "plan-1"}}

    def post(url: str, **kwargs: object) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_settings",
        lambda: InspectionSettings(
            _env_file=None,
            plan_detail_url="http://inspection.local/plan/detail",
            api_timeout_seconds=12,
            allcore_auth_token="plan-token",
        ),
    )
    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_allcore_auth_client",
        lambda: InspectionAllCoreAuthClient(
            InspectionSettings(_env_file=None, allcore_auth_token="plan-token")
        ),
    )
    monkeypatch.setattr("httpx.post", post)

    result = inspection_query_plan_detail.invoke({"plan_id": "plan-1"})

    assert result == {"ok": True, "planId": "plan-1", "plan": {"planGuid": "plan-1"}}
    assert calls == [
        {
            "url": "http://inspection.local/plan/detail",
            "json": {"id": "plan-1"},
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "allcore-auth": "bearer plan-token",
            },
            "timeout": 12.0,
        }
    ]


def test_inspection_query_coverage_uses_integration_datasource(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def query(
            self,
            datasource: str,
            question: str,
        ) -> dict[str, object]:
            calls.append({"datasource": datasource, "question": question})
            return {"status": "success", "data": {"rows": []}}

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_settings",
        lambda: InspectionSettings(
            _env_file=None,
            text_to_sql_datasource="inspection_mysql",
        ),
    )
    monkeypatch.setattr("app.integrations.inspection.workflows.TextToSqlClient", FakeClient)

    result = inspection_query_coverage.invoke({"line_name": "线路A"})

    assert result["ok"] is True
    assert calls == [
        {
            "datasource": "inspection_mysql",
            "question": "查询线路名称为'线路A'的杆塔、航迹和机场覆盖情况",
        }
    ]


def test_inspection_plan_coverage_rebuilds_legacy_tower_route_airport_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    questions: list[str] = []

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def query(self, datasource: str, question: str) -> dict[str, object]:
            assert datasource == "inspection_mysql"
            questions.append(question)
            if "计划 plan_guid" in question:
                rows = [
                    {
                        "device_guid": "tower-1",
                        "device_name": "1号杆塔",
                        "parent_device_guid": "line-1",
                        "parent_device_name": "10kV白路线",
                        "major": "dms",
                        "longitude": 120.001,
                        "latitude": 30.001,
                    },
                    {
                        "device_guid": "tower-2",
                        "device_name": "2号杆塔",
                        "parent_device_guid": "line-1",
                        "parent_device_name": "10kV白路线",
                        "major": "dms",
                        "longitude": 121.0,
                        "latitude": 31.0,
                    },
                ]
            elif "所有航迹信息" in question:
                rows = [{
                    "id": 101,
                    "create_user": "creator-1",
                    "create_time": "2026-08-01 10:00:00",
                    "update_user": "updater-1",
                    "update_time": "2026-08-02 11:00:00",
                    "dept_code": "001",
                    "is_deleted": 0,
                    "create_dept": "dept-1",
                    "device_guid": "tower-1",
                    "parent_device_guid": "line-1",
                    "route_guid": "route-1",
                    "route_description": "主航线",
                    "description": "1号杆塔航迹",
                    "file_guid": "file-1",
                    "route_version_type": "formal",
                    "route_type": "tower",
                    "device_type": "dms",
                    "route_source": "platform",
                    "adapted_model": "M350",
                    "track_version": "3",
                    "track_type": "fine",
                    "route_content": "route-content-1",
                    "file_type": "json",
                    "upload_source": "system",
                }]
            else:
                rows = [{
                    "dock_guid": "dock-1",
                    "dock_name": "机场1",
                    "longitude": 120.0,
                    "latitude": 30.0,
                    "inspection_radius": 3000,
                }]
            return {"status": "success", "data": {"result": {"rows": rows}}}

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_settings",
        lambda: InspectionSettings(
            _env_file=None,
            text_to_sql_datasource="inspection_mysql",
        ),
    )
    monkeypatch.setattr("app.integrations.inspection.workflows.TextToSqlClient", FakeClient)

    result = inspection_query_coverage.invoke({"plan_guid": "plan-guid-1"})

    assert result["ok"] is True
    assert result["coveredCount"] == 1
    assert result["uncoveredCount"] == 1
    assert result["coveredRows"][0]["deviceGuid"] == "tower-1"
    assert result["coveredRows"][0]["parentDeviceGuid"] == "line-1"
    assert result["coveredRows"][0]["deviceRouteList"] == [{
        "id": 101,
        "createUser": "creator-1",
        "createTime": "2026-08-01 10:00:00",
        "updateUser": "updater-1",
        "updateTime": "2026-08-02 11:00:00",
        "deptCode": "001",
        "isDeleted": 0,
        "createDept": "dept-1",
        "routeGuid": "route-1",
        "parentDeviceGuid": "line-1",
        "deviceGuid": "tower-1",
        "routeDescription": "主航线",
        "description": "1号杆塔航迹",
        "fileGuid": "file-1",
        "routeVersionType": "formal",
        "routeType": "tower",
        "deviceType": "dms",
        "routeSource": "platform",
        "adaptedModel": "M350",
        "trackVersion": "3",
        "trackType": "fine",
        "routeContent": "route-content-1",
        "fileType": "json",
        "uploadSource": "system",
    }]
    assert result["coveredRows"][0]["dockGuid"] == "dock-1"
    assert result["coveredRows"][0]["routeGuid"] == "route-1"
    assert "createUser" not in result["coveredRows"][0]
    assert result["uncoveredRows"][0]["deviceGuid"] == "tower-2"
    assert len(questions) == 3


def test_inspection_verifies_created_work_order_with_integration_datasource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, str]] = []

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def query(self, datasource: str, question: str) -> dict[str, object]:
            calls.append({"datasource": datasource, "question": question})
            if "已创建成功的所有巡检工单" in question:
                return {
                    "status": "success",
                    "data": {"rows": [{
                        "id": "order-1",
                        "inspection_method": "dock",
                    }]},
                }
            return {
                "status": "success",
                "data": {"rows": [{
                    "work_order_no": "WO-1",
                    "status": "created",
                    "inspection_method": "dock",
                    "plan_guid": "plan-guid-1",
                    "plan_name": "白路线巡检",
                    "plan_type": "5",
                    "inspect_start_time": "2026-08-18 08:00:00",
                    "inspect_end_time": "2026-08-18 18:00:00",
                }]},
            }

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_settings",
        lambda: InspectionSettings(
            _env_file=None,
            text_to_sql_datasource="inspection_mysql",
        ),
    )
    monkeypatch.setattr("app.integrations.inspection.workflows.TextToSqlClient", FakeClient)

    result = inspection_query_work_order_detail.invoke({"order_id": "order-1"})

    assert result["ok"] is True
    assert result["workOrder"]["work_order_no"] == "WO-1"
    assert result["planGuid"] == "plan-guid-1"
    assert result["completedGroups"] == ["covered"]
    assert result["createdWorkOrders"] == [{
        "id": "order-1",
        "inspection_method": "dock",
        "work_order_no": "WO-1",
        "status": "created",
        "plan_guid": "plan-guid-1",
        "plan_name": "白路线巡检",
        "plan_type": "5",
        "inspect_start_time": "2026-08-18 08:00:00",
        "inspect_end_time": "2026-08-18 18:00:00",
    }]
    assert result["plan"] == {
        "planGuid": "plan-guid-1",
        "planName": "白路线巡检",
        "planType": "5",
        "inspectStartTime": "2026-08-18 08:00:00",
        "inspectEndTime": "2026-08-18 18:00:00",
    }
    assert calls[0]["datasource"] == "inspection_mysql"
    assert "id=order-1" in calls[0]["question"]
    assert "关联计划guid" in calls[0]["question"]
    assert calls[1]["datasource"] == "inspection_mysql"
    assert "plan_guid=plan-guid-1" in calls[1]["question"]


def test_inspection_work_order_verification_accumulates_all_completed_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def query(self, datasource: str, question: str) -> dict[str, object]:
            if "已创建成功的所有巡检工单" in question:
                rows = [
                    {"id": "order-covered", "inspection_method": "dock"},
                    {"id": "order-uncovered", "inspection_method": "drone"},
                ]
            else:
                rows = [{
                    "work_order_no": "WO-2",
                    "inspection_method": "drone",
                    "plan_guid": "plan-guid-1",
                    "plan_type": "5",
                    "inspect_start_time": "2026-08-18 08:00:00",
                    "inspect_end_time": "2026-08-18 18:00:00",
                }]
            return {"status": "success", "data": {"rows": rows}}

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_settings",
        lambda: InspectionSettings(
            _env_file=None,
            text_to_sql_datasource="inspection_mysql",
        ),
    )
    monkeypatch.setattr("app.integrations.inspection.workflows.TextToSqlClient", FakeClient)

    result = inspection_query_work_order_detail.invoke({"order_id": "order-uncovered"})

    assert result["ok"] is True
    assert result["completedGroup"] == "uncovered"
    assert result["completedGroups"] == ["covered", "uncovered"]


def test_inspection_query_device_data_uses_legacy_question_and_maps_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            return None

        def query(
            self,
            datasource: str,
            question: str,
        ) -> dict[str, object]:
            calls.append({"datasource": datasource, "question": question})
            return {
                "status": "success",
                "data": {
                    "rows": [{
                        "tower_guid": "tower-guid-3",
                        "basic_tower_ledger_name": "10kV十九线#3",
                        "major": "tms",
                        "line_guid": "line-guid-19",
                        "basic_line_ledger_name": "10kV十九线",
                    }]
                },
            }

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_settings",
        lambda: InspectionSettings(
            _env_file=None,
            text_to_sql_datasource="inspection_mysql",
        ),
    )
    monkeypatch.setattr("app.integrations.inspection.workflows.TextToSqlClient", FakeClient)

    result = inspection_query_device_data.invoke({"parent_device_name": "10kV十九线", "ranges": "#3"})

    assert result["ok"] is True
    assert result["question"] == "查询10kV十九线线路下#3的杆塔uid、杆塔名称、杆塔专业、线路uid、线路名称"
    assert calls == [{
        "datasource": "inspection_mysql",
        "question": "查询10kV十九线线路下#3的杆塔uid、杆塔名称、杆塔专业、线路uid、线路名称",
    }]
    assert result["planObjectListRef"] == "current_query_result"
    assert result["count"] == 1
    assert result["planObjectListNames"] == ["10kV十九线#3"]


def test_inspection_large_device_query_keeps_objects_out_of_model_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Client:
        def query(self, *, datasource: str, question: str) -> dict[str, object]:
            return {
                "status": "success",
                "data": {"rows": [{
                    "tower_guid": f"tower-{index}",
                    "basic_tower_ledger_name": f"杆塔{index}",
                    "major": "dms",
                    "line_guid": "line-1",
                    "basic_line_ledger_name": "线路1",
                } for index in range(1, 91)]},
            }

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.TextToSqlClient",
        lambda *args: Client(),
    )
    token = set_runtime_context(RequestRuntimeContext(session_id="session-1", metadata={}))
    try:
        result = inspection_query_device_data.invoke({"parent_device_name": "线路1"})
        assert result["count"] == 90
        assert "planObjectList" not in result
        assert result["planObjectListRef"] == "current_query_result"

        fill_state = inspection_build_plan_fill_state.invoke({
            "plan_type": "5",
            "plan_object_ref": "current_query_result",
            "inspect_start_time": "2026-08-18 08:00:00",
            "inspect_end_time": "2026-08-18 10:00:00",
        })
        assert fill_state["ok"] is True
        assert len(fill_state["executePayload"]["planObjectList"]) == 90
    finally:
        reset_runtime_context(token)


def test_inspection_plan_fill_state_uses_cached_objects_when_model_stringifies_list() -> None:
    cached = [{
        "deviceGuid": "tower-1",
        "deviceName": "10kV白路线#1",
        "major": "dms",
        "parentDeviceGuid": "line-1",
        "parentDeviceName": "10kV白路线",
    }]
    token = set_runtime_context(
        RequestRuntimeContext(
            session_id="session-1",
            metadata={"_inspection_current_plan_objects": cached},
        )
    )
    try:
        result = inspection_build_plan_fill_state.invoke({
            "plan_type": "临时巡检",
            "plan_object_list": '[{"deviceGuid":"fake-name","parentDeviceGuid":"fake-line"}]',
            "inspect_start_time": "2026-08-23 00:00:00",
            "inspect_end_time": "2026-08-23 23:59:59",
        })
        assert result["ok"] is True
        assert result["executePayload"]["planObjectList"] == cached
    finally:
        reset_runtime_context(token)


@pytest.mark.asyncio
async def test_inspection_adapter_returns_frontend_callback_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_if_http_client_is_used(*args: object, **kwargs: object) -> None:
        raise AssertionError("inspection write actions must be executed by the frontend")

    monkeypatch.setattr("httpx.AsyncClient", fail_if_http_client_is_used)
    result = await InspectionAdapter().invoke(
        "create_work_order",
        {
            "plan_guid": "plan-1",
            "inspection_method": "dock",
            "start_date": "2026-08-14 08:00:00",
            "end_date": "2026-08-14 10:00:00",
        },
        ActionExecutionContext(session_id="session-1"),
    )

    assert result["executionMode"] == "frontend_callback"
    assert result["actionCode"] == "createTempOrder"
    assert result["executeApi"] == "/order/createTempOrder"
    assert result["executeMethod"] == "POST"
    assert result["executePayload"] == {
        "planGuid": "plan-1",
        "inspectionMethod": "dock",
        "startDate": "2026-08-14 08:00:00",
        "endDate": "2026-08-14 10:00:00",
    }


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
