"""Model-facing action contracts for the inspection system."""

from app.actions.schemas import (
    ActionConfirmation,
    ActionExecutorSpec,
    ActionInputSpec,
    ActionSpec,
)
from app.integrations.inspection.models import (
    CreateInspectionPlanInput,
    CreateInspectionWorkOrderInput,
    FlyInspectionWorkOrderInput,
)


CREATE_PLAN = ActionSpec(
    action_id="inspection.create_plan",
    title="创建巡检计划",
    description=(
        "在巡检系统中创建计划，并绑定已确认的线路和杆塔。"
        "planObjectList 必须来自 inspection_query_device_data 返回的真实 planObjectList，"
        "planType、planName 和完整参数必须来自 inspection_build_plan_fill_state 的 executePayload，"
        "不得由模型自行根据线路名或杆塔名编造 deviceGuid/parentDeviceGuid。"
        "真实 createPlan actionResult 返回计划 ID 后，由巡检插件继续校验计划并拆分工单。"
    ),
    system="inspection",
    inputs=[
        ActionInputSpec("planType", description="计划类型字典键，例如临时计划为 5"),
        ActionInputSpec("planName", description="按规则生成的唯一计划名称"),
        ActionInputSpec("inspectStartTime", description="开始时间"),
        ActionInputSpec("inspectEndTime", description="结束时间"),
        ActionInputSpec(
            "planObjectList",
            type="array",
            description="巡检杆塔列表，必须直接使用 inspection_query_device_data 返回的 planObjectList",
        ),
    ],
    input_model=CreateInspectionPlanInput,
    executor=ActionExecutorSpec(adapter="inspection", method="create_plan"),
    intent_examples=["创建巡检计划", "新建线路巡检计划"],
    pre_checks=["inspection.valid_time_window"],
    confirmation=ActionConfirmation(required=True),
    risk_level="medium",
    success_template="巡检计划已创建：{planGuid}",
)

CREATE_WORK_ORDER = ActionSpec(
    action_id="inspection.create_work_order",
    title="创建巡检工单",
    description="仅在用户明确要求创建工单时，基于已确认的巡检计划和杆塔明细创建一张巡检工单。",
    system="inspection",
    inputs=[
        ActionInputSpec("planGuid", description="巡检计划 GUID"),
        ActionInputSpec("inspectionMethod", description="dock 或 drone"),
        ActionInputSpec("startDate", description="开始时间"),
        ActionInputSpec("endDate", description="结束时间"),
        ActionInputSpec("orderDetailList", type="array", description="本工单的杆塔明细"),
    ],
    input_model=CreateInspectionWorkOrderInput,
    executor=ActionExecutorSpec(adapter="inspection", method="create_work_order"),
    intent_examples=["创建巡检工单", "安排无人机巡检", "生成巡检任务"],
    pre_checks=[],
    confirmation=ActionConfirmation(required=True),
    risk_level="high",
    success_template="巡检工单已创建：{id}",
)


FLY_WORK_ORDER = ActionSpec(
    action_id="inspection.fly_work_order",
    title="巡检工单一键起飞",
    description="对已创建并校验成功的固定机场巡检工单执行一键起飞。",
    system="inspection",
    inputs=[
        ActionInputSpec("ids", type="array", description="固定机场巡检工单 ID 列表"),
        ActionInputSpec("workOrderNo", description="用于确认界面展示的工单编号", required=False),
        ActionInputSpec("finalSummary", description="已创建工单的真实汇总，仅用于确认界面展示", required=False),
    ],
    input_model=FlyInspectionWorkOrderInput,
    executor=ActionExecutorSpec(adapter="inspection", method="fly_work_order"),
    intent_examples=["一键起飞", "执行巡检工单", "启动无人机巡检任务"],
    confirmation=ActionConfirmation(required=True),
    risk_level="high",
    success_template="巡检工单起飞操作已提交",
)
