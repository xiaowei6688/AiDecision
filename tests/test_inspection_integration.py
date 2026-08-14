import pytest

from app.actions.policy import PolicyEngine
from app.actions.schemas import ActionExecutionContext
from app.integrations.inspection.actions import CREATE_PLAN, CREATE_WORK_ORDER
from app.integrations.inspection.notifications import (
    InspectionNotificationRequest,
    build_notification_event,
)
from app.integrations.inspection.checks import valid_time_window
from app.integrations.inspection.models import CreateInspectionPlanInput, CreateInspectionWorkOrderInput
from app.integrations.inspection.adapter import InspectionAdapter
from app.integrations.inspection.auth import InspectionAuthClient
from app.integrations.inspection.config import InspectionSettings
from app.integrations.inspection.ui import (
    inspection_action_result_projection,
    inspection_frontend_callback_resume_projection,
    inspection_human_interrupt_projection,
)
from app.integrations.inspection.workflows import (
    inspection_query_coverage,
    inspection_query_device_data,
    inspection_query_plan_detail,
)
from app.actions.schemas import ActionResult
from app.integrations.projections import (
    project_action_result,
    project_human_interrupt,
    register_action_result_projection,
    register_human_interrupt_projection,
)
from app.integrations.tools import tool_step


def test_inspection_actions_are_confirmed_writes() -> None:
    assert CREATE_PLAN.confirmation.required
    assert CREATE_WORK_ORDER.confirmation.required
    assert CREATE_WORK_ORDER.executor.adapter == "inspection"


def test_inspection_registers_user_friendly_tool_steps() -> None:
    from app.integrations.inspection.registration import register_inspection_tools

    register_inspection_tools()

    step = tool_step("inspection_query_device_data")
    assert step.title == "核对线路杆塔台账"
    assert step.summary == "正在按线路和范围核对杆塔 UID、名称、专业及所属线路"


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

    register_human_interrupt_projection(inspection_human_interrupt_projection)
    projected = project_human_interrupt([interrupt])

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
                "planGuid": "plan-1",
            },
        },
    )

    assert projected["status"] == "success"
    assert projected["message"] == "计划已创建"
    assert projected["data"]["createdPlanGuid"] == "plan-1"
    assert projected["data"]["final"] is True
    assert "明确发起创建工单" in projected["data"]["nextUserAction"]


def test_inspection_work_order_frontend_callback_requires_action_result() -> None:
    projected = inspection_frontend_callback_resume_projection(
        {
            "status": "requires_confirmation",
            "action_id": "inspection.create_work_order",
            "actionCode": "createTempOrder",
            "executePayload": {"planGuid": "plan-1"},
        },
        {
            "action": "approve",
            "content": "确认执行此操作",
            "data": {},
        },
    )

    assert projected["status"] == "failed"
    assert projected["error_code"] == "ACTION_RESULT_REQUIRED"
    assert "actionResult" in projected["message"]


def test_inspection_auth_client_fetches_and_caches_login_token(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class Response:
        text = '{"access_token":"login-token"}'

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"access_token": "login-token"}

    def post(url: str, **kwargs: object) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr("httpx.post", post)
    settings = InspectionSettings(
        _env_file=None,
        auth_login_url="http://inspection.local/oauth/token",
        auth_username="user",
        auth_password="password",
        basic_auth="basic-secret",
        tenant_id="tenant-1",
    )
    client = InspectionAuthClient(settings)

    headers = client.headers_sync()
    cached_headers = client.headers_sync()

    assert headers["allcore-auth"] == "bearer login-token"
    assert headers["Authorization"] == "Basic basic-secret"
    assert headers["Tenant-Id"] == "tenant-1"
    assert cached_headers["allcore-auth"] == "bearer login-token"
    assert len(calls) == 1
    assert calls[0]["url"] == "http://inspection.local/oauth/token"
    assert calls[0]["params"] == {
        "tenantId": "tenant-1",
        "username": "user",
        "password": "password",
        "grant_type": "password",
        "type": "account",
        "scope": "all",
    }


def test_inspection_plan_detail_uses_allcore_auth_header(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class AuthClient:
        def headers_sync(self) -> dict[str, str]:
            return {"allcore-auth": "bearer static-token", "Tenant-Id": "tenant-1"}

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"data": {"planGuid": "plan-1"}}

    def post(url: str, **kwargs: object) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(
        "app.integrations.inspection.workflows.get_inspection_settings",
        lambda: InspectionSettings(
            _env_file=None,
            plan_detail_url="http://inspection.local/plan/detail",
            api_timeout_seconds=12,
        ),
    )
    monkeypatch.setattr("app.integrations.inspection.workflows.get_inspection_auth_client", lambda: AuthClient())
    monkeypatch.setattr("httpx.post", post)

    result = inspection_query_plan_detail.invoke({"plan_id": "plan-1"})

    assert result == {"ok": True, "planId": "plan-1", "plan": {"planGuid": "plan-1"}}
    assert calls == [
        {
            "url": "http://inspection.local/plan/detail",
            "json": {"id": "plan-1"},
            "headers": {"allcore-auth": "bearer static-token", "Tenant-Id": "tenant-1"},
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
    assert result["planObjectList"] == [{
        "deviceGuid": "tower-guid-3",
        "deviceName": "10kV十九线#3",
        "major": "tms",
        "parentDeviceGuid": "line-guid-19",
        "parentDeviceName": "10kV十九线",
    }]


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
