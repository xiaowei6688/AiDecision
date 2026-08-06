from app.actions.registry import ActionRegistry
from app.actions.schemas import (
    ActionConfirmation,
    ActionExecutorSpec,
    ActionInputSpec,
    ActionSpec,
)


def register_actions(registry: ActionRegistry, adapter_name: str) -> None:
    registry.register(
        ActionSpec(
            action_id="hr.create_leave_request",
            title="创建请假申请",
            description="在员工管理系统中创建请假申请。",
            system="hr",
            intent_examples=[
                "帮张三请假",
                "给李四创建年假申请",
                "提交员工请假单",
            ],
            inputs=[
                ActionInputSpec(
                    name="employee_id",
                    description="员工 ID，可通过 semantic_query 从姓名或工号解析。",
                    resolver="semantic_query:hr",
                ),
                ActionInputSpec(
                    name="start_time",
                    type="datetime",
                    description="请假开始时间。",
                ),
                ActionInputSpec(
                    name="end_time",
                    type="datetime",
                    description="请假结束时间。",
                ),
                ActionInputSpec(
                    name="reason",
                    description="请假原因。",
                ),
            ],
            pre_checks=["hr.employee_id_present"],
            confirmation=ActionConfirmation(
                required=True,
                template="确认创建请假申请：{{employee_id}} 从 {{start_time}} 到 {{end_time}}？",
            ),
            risk_level="medium",
            executor=ActionExecutorSpec(
                adapter=adapter_name,
                method="create_leave_request",
            ),
            success_template="请假申请已创建，申请号：{{leave_id}}",
        )
    )
