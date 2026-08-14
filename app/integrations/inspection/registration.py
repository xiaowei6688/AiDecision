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
from app.integrations.inspection.ui import inspection_action_result_projection, inspection_human_interrupt_projection
from app.integrations.inspection.workflows import (
    inspection_build_work_order_fill_state,
    inspection_query_coverage,
    inspection_query_device_data,
    inspection_query_plan_detail,
)
from app.integrations.projections import register_action_result_projection, register_human_interrupt_projection
from app.integrations.tools import register_integration_tool


def register_inspection_actions(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> None:
    registry.register(CREATE_PLAN)
    registry.register(CREATE_WORK_ORDER)
    executor.register_adapter("inspection", InspectionAdapter())
    policy_engine.register_pre_check("inspection.valid_time_window", valid_time_window)


def register_inspection_projections() -> None:
    register_action_result_projection(inspection_action_result_projection)
    register_human_interrupt_projection(inspection_human_interrupt_projection)


def register_inspection_tools() -> None:
    register_integration_tool(inspection_query_plan_detail)
    register_integration_tool(inspection_query_device_data)
    register_integration_tool(inspection_query_coverage)
    register_integration_tool(inspection_build_work_order_fill_state)


def register_inspection_agents(registry: Any) -> None:
    registry.register(inspection_agent)


def inspection_routers() -> Sequence[APIRouter]:
    return [inspection_router]
