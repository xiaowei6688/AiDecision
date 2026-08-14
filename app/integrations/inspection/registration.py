"""Inspection integration registration helpers."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter

from app.integrations.inspection.actions import CREATE_PLAN, CREATE_WORK_ORDER
from app.integrations.inspection.adapter import InspectionAdapter
from app.integrations.inspection.agent import inspection_agent
from app.integrations.inspection.checks import valid_time_window
from app.integrations.inspection.routes import router as inspection_router
from app.integrations.inspection.ui import (
    inspection_action_result_projection,
    inspection_frontend_callback_resume_projection,
    inspection_human_interrupt_projection,
)
from app.integrations.inspection.websocket_actions import inspection_work_order_action_result_to_resume
from app.integrations.inspection.workflows import (
    inspection_build_work_order_fill_state,
    inspection_query_coverage,
    inspection_query_device_data,
    inspection_query_plan_detail,
)
from app.integrations.context import PluginContext


def register_inspection_actions(context: PluginContext) -> None:
    context.action_registry.register(CREATE_PLAN)
    context.action_registry.register(CREATE_WORK_ORDER)
    context.action_executor.register_adapter("inspection", InspectionAdapter())
    context.policy_engine.register_pre_check("inspection.valid_time_window", valid_time_window)


def register_inspection_projections(context: PluginContext) -> None:
    context.projections.register_action_result(inspection_action_result_projection)
    context.projections.register_human_interrupt(inspection_human_interrupt_projection)
    context.projections.register_frontend_callback(
        inspection_frontend_callback_resume_projection
    )
    context.action_results.register(inspection_work_order_action_result_to_resume)


def register_inspection_tools(context: PluginContext) -> None:
    for item in (
        inspection_query_plan_detail,
        inspection_query_device_data,
        inspection_query_coverage,
        inspection_build_work_order_fill_state,
    ):
        context.tools.register(item)
    for name, title, summary in (
        ("inspection_query_plan_detail", "核对巡检计划详情", "正在核对计划的真实台账信息和后续工单条件"),
        ("inspection_query_device_data", "核对线路杆塔台账", "正在按线路和范围核对杆塔 UID、名称、专业及所属线路"),
        ("inspection_query_coverage", "分析巡检覆盖条件", "正在结合机场覆盖情况判断可用的巡检方式"),
        ("inspection_build_work_order_fill_state", "整理工单确认信息", "正在把计划、设备和巡检方式整理成待确认的工单数据"),
    ):
        context.tools.register_step(name, title, summary)


def register_inspection_agent(context: PluginContext) -> None:
    if not context.business_agent_registry.contains(inspection_agent.business_id):
        context.business_agent_registry.register(inspection_agent)


def inspection_routers() -> Sequence[APIRouter]:
    return [inspection_router]
