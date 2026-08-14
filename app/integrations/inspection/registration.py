"""Inspection integration registration helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter

from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
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
from app.integrations.projections import (
    register_action_result_projection,
    register_frontend_callback_resume_projection,
    register_human_interrupt_projection,
)
from app.integrations.websocket_actions import register_action_result_handler
from app.integrations.tools import register_integration_tool, register_tool_step
from app.integrations.context import PluginContext
from app.integrations.tools import build_tool_step


def register_inspection_actions(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> None:
    registry.register(CREATE_PLAN)
    registry.register(CREATE_WORK_ORDER)
    executor.register_adapter("inspection", InspectionAdapter())
    policy_engine.register_pre_check("inspection.valid_time_window", valid_time_window)


def register_inspection_projections(context: PluginContext | None = None) -> None:
    if context is not None:
        context.register_projection(context.action_result_projections, inspection_action_result_projection)
        context.register_projection(context.human_interrupt_projections, inspection_human_interrupt_projection)
        context.register_projection(context.frontend_callback_projections, inspection_frontend_callback_resume_projection)
        context.register_handler(inspection_work_order_action_result_to_resume)
        return
    register_action_result_projection(inspection_action_result_projection)
    register_human_interrupt_projection(inspection_human_interrupt_projection)
    register_frontend_callback_resume_projection(inspection_frontend_callback_resume_projection)
    register_action_result_handler(inspection_work_order_action_result_to_resume)


def register_inspection_tools(context: PluginContext | None = None) -> None:
    if context is not None:
        for item in (
            inspection_query_plan_detail,
            inspection_query_device_data,
            inspection_query_coverage,
            inspection_build_work_order_fill_state,
        ):
            context.register_tool(item)
        for name, title, summary in (
            ("inspection_query_plan_detail", "核对巡检计划详情", "正在核对计划的真实台账信息和后续工单条件"),
            ("inspection_query_device_data", "核对线路杆塔台账", "正在按线路和范围核对杆塔 UID、名称、专业及所属线路"),
            ("inspection_query_coverage", "分析巡检覆盖条件", "正在结合机场覆盖情况判断可用的巡检方式"),
            ("inspection_build_work_order_fill_state", "整理工单确认信息", "正在把计划、设备和巡检方式整理成待确认的工单数据"),
        ):
            description = build_tool_step(name, title, summary)
            if description is not None:
                context.register_tool_step(name, description)
        return
    register_integration_tool(inspection_query_plan_detail)
    register_integration_tool(inspection_query_device_data)
    register_integration_tool(inspection_query_coverage)
    register_integration_tool(inspection_build_work_order_fill_state)
    register_tool_step(
        "inspection_query_plan_detail",
        "核对巡检计划详情",
        "正在核对计划的真实台账信息和后续工单条件",
    )
    register_tool_step(
        "inspection_query_device_data",
        "核对线路杆塔台账",
        "正在按线路和范围核对杆塔 UID、名称、专业及所属线路",
    )
    register_tool_step(
        "inspection_query_coverage",
        "分析巡检覆盖条件",
        "正在结合机场覆盖情况判断可用的巡检方式",
    )
    register_tool_step(
        "inspection_build_work_order_fill_state",
        "整理工单确认信息",
        "正在把计划、设备和巡检方式整理成待确认的工单数据",
    )


def register_inspection_agents(registry: Any) -> None:
    if not registry.contains(inspection_agent.business_id):
        registry.register(inspection_agent)


def inspection_routers() -> Sequence[APIRouter]:
    return [inspection_router]
