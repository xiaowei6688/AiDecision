from app.actions.registry import ActionRegistry
from app.actions.schemas import (
    ActionConfirmation,
    ActionExecutorSpec,
    ActionInputSpec,
    ActionSpec,
)
from app.integrations.inspection.models import InspectionTaskCommand


def register_actions(registry: ActionRegistry, adapter_name: str) -> None:
    registry.register(
        ActionSpec(
            action_id="inspection.create_task",
            title="创建巡检任务",
            description="为指定设备创建巡检任务，并分配给指定员工。",
            system="inspection",
            intent_examples=[
                "安排张三明天去巡检空压机",
                "给三号车间设备创建一个巡检任务",
                "让维修班看一下这台设备",
            ],
            inputs=[
                ActionInputSpec(
                    name="device_id",
                    description="设备唯一标识，可通过 semantic_query 从设备名称解析。",
                    resolver="semantic_query:inspection",
                ),
                ActionInputSpec(
                    name="assignee_id",
                    description="负责人员工 ID，可通过 semantic_query 从姓名解析。",
                    resolver="semantic_query:hr",
                ),
                ActionInputSpec(
                    name="due_time",
                    type="datetime",
                    description="巡检截止或计划执行时间。",
                ),
            ],
            pre_checks=["inspection.device_id_present", "inspection.assignee_id_present"],
            confirmation=ActionConfirmation(
                required=True,
                template="确认创建巡检任务：{{assignee_id}} 在 {{due_time}} 巡检 {{device_id}}？",
            ),
            risk_level="medium",
            executor=ActionExecutorSpec(
                adapter=adapter_name,
                method="create_task",
            ),
            success_template="巡检任务已创建，任务号：{{task_id}}",
            input_model=InspectionTaskCommand,
        )
    )
