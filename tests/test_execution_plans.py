import pytest

from app.actions.bootstrap import bootstrap_actions
from app.actions.registry import default_action_registry
from app.domain.plans import ExecutionPlan, validate_execution_plan


def test_execution_plan_validates_cross_system_dependencies_and_command_params() -> None:
    bootstrap_actions()
    plan = ExecutionPlan(
        goal="确认人员可用后安排巡检",
        steps=[
            {
                "step_id": "check-employee",
                "kind": "query",
                "datasource": "hr",
                "question": "查询 E100 明天是否可用",
                "rationale": "巡检任务需要有效负责人",
            },
            {
                "step_id": "create-task",
                "kind": "action",
                "action_id": "inspection.create_task",
                "params": {
                    "device_id": "D100",
                    "assignee_id": "E100",
                    "due_time": "2026-08-08T09:00:00",
                },
                "depends_on": ["check-employee"],
                "rationale": "人员可用后创建巡检任务",
            },
        ],
    )

    validated = validate_execution_plan(plan, default_action_registry, {"erp", "hr", "inspection"})

    assert validated.status == "planned"
    assert validated.steps[1].params["due_time"] == "2026-08-08T09:00:00"


def test_execution_plan_rejects_dependency_cycles() -> None:
    plan = ExecutionPlan(
        goal="无效计划",
        steps=[
            {
                "step_id": "a",
                "kind": "query",
                "datasource": "hr",
                "question": "查询人员",
                "depends_on": ["b"],
                "rationale": "测试",
            },
            {
                "step_id": "b",
                "kind": "query",
                "datasource": "hr",
                "question": "查询排班",
                "depends_on": ["a"],
                "rationale": "测试",
            },
        ],
    )

    with pytest.raises(ValueError, match="cycle"):
        validate_execution_plan(plan, default_action_registry, {"hr"})


def test_execution_plan_rejects_unknown_datasource() -> None:
    plan = ExecutionPlan(
        goal="查询 CRM",
        steps=[
            {
                "step_id": "crm-query",
                "kind": "query",
                "datasource": "crm",
                "question": "查询客户",
                "rationale": "测试",
            },
        ],
    )

    with pytest.raises(ValueError, match="unknown datasource"):
        validate_execution_plan(plan, default_action_registry, {"erp", "hr"})
