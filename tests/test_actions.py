import pytest

from app.actions.bootstrap import bootstrap_actions
from app.actions.executor import default_action_executor
from app.actions.registry import default_action_registry
from app.actions.schemas import ActionExecutionContext
from app.adapters.text_to_sql import TextToSqlClient


def test_default_actions_are_registered() -> None:
    bootstrap_actions()

    actions = default_action_registry.search("采购滤芯")

    assert any(action.action_id == "erp.create_purchase_request" for action in actions)


@pytest.mark.asyncio
async def test_business_action_requires_confirmation() -> None:
    bootstrap_actions()

    result = await default_action_executor.execute(
        action_id="inspection.create_task",
        params={
            "device_id": "D100",
            "assignee_id": "E100",
            "due_time": "2026-08-07 09:00",
        },
        context=ActionExecutionContext(user_id="tester"),
    )

    assert result.status == "requires_confirmation"
    assert result.action_id == "inspection.create_task"


@pytest.mark.asyncio
async def test_business_action_rejects_invalid_domain_command_before_adapter() -> None:
    bootstrap_actions()

    result = await default_action_executor.execute(
        action_id="hr.create_leave_request",
        params={
            "employee_id": "E100",
            "start_time": "2026-08-08T10:00:00",
            "end_time": "2026-08-08T09:00:00",
            "reason": "年假",
        },
        context=ActionExecutionContext(user_id="tester"),
    )

    assert result.status == "failed"
    assert result.error_code == "INVALID_PARAMS"


def test_action_catalog_exposes_domain_input_schema() -> None:
    bootstrap_actions()

    action = default_action_registry.get("inspection.create_task")
    schema = action.public_dict()["input_schema"]

    assert schema is not None
    assert set(schema["required"]) == {"device_id", "assignee_id", "due_time"}


@pytest.mark.asyncio
async def test_business_action_executes_with_bound_confirmation_token() -> None:
    bootstrap_actions()

    params = {
        "material_id": "M100",
        "quantity": 3,
        "reason": "备件不足",
    }
    context = ActionExecutionContext(user_id="tester", session_id="session-1")
    pending = await default_action_executor.execute(
        action_id="erp.create_purchase_request",
        params=params,
        context=context,
    )

    result = await default_action_executor.execute(
        action_id="erp.create_purchase_request",
        params=params,
        context=context,
        confirmation_token=pending.data["confirmation_token"],
    )

    assert result.status == "success"
    assert result.data["request_id"] == "ERP-DEMO-001"


@pytest.mark.asyncio
async def test_confirmation_token_cannot_authorize_changed_params_or_session() -> None:
    bootstrap_actions()
    params = {"material_id": "M100", "quantity": 3, "reason": "备件不足"}
    pending = await default_action_executor.execute(
        action_id="erp.create_purchase_request",
        params=params,
        context=ActionExecutionContext(user_id="tester", session_id="session-1"),
    )

    result = await default_action_executor.execute(
        action_id="erp.create_purchase_request",
        params={**params, "quantity": 4},
        context=ActionExecutionContext(user_id="tester", session_id="session-2"),
        confirmation_token=pending.data["confirmation_token"],
    )

    assert result.status == "requires_confirmation"


@pytest.mark.asyncio
async def test_confirmation_token_can_only_be_consumed_once() -> None:
    bootstrap_actions()
    params = {"material_id": "M100", "quantity": 3, "reason": "备件不足"}
    context = ActionExecutionContext(user_id="tester", session_id="session-1")
    pending = await default_action_executor.execute(
        action_id="erp.create_purchase_request", params=params, context=context
    )
    token = pending.data["confirmation_token"]

    first = await default_action_executor.execute(
        action_id="erp.create_purchase_request", params=params, context=context,
        confirmation_token=token,
    )
    second = await default_action_executor.execute(
        action_id="erp.create_purchase_request", params=params, context=context,
        confirmation_token=token,
    )

    assert first.status == "success"
    assert second.status == "requires_confirmation"


def test_text_to_sql_client_reports_missing_configuration() -> None:
    result = TextToSqlClient(base_url=None).query(
        datasource="erp",
        question="查询滤芯库存",
    )

    assert result["status"] == "failed"
    assert result["error_code"] == "TEXT_TO_SQL_NOT_CONFIGURED"
