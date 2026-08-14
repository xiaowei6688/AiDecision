"""Inspection integration bundle."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter

from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.integrations.inspection.registration import (
    inspection_routers,
    register_inspection_actions,
    register_inspection_agents,
    register_inspection_projections,
    register_inspection_tools,
)
from app.integrations.inspection.lifecycle import InspectionLifecycle


class InspectionBundle:
    name = "inspection"

    def __init__(self) -> None:
        self._lifecycle = InspectionLifecycle()

    def register(
        self,
        registry: ActionRegistry,
        executor: BusinessActionExecutor,
        policy_engine: PolicyEngine,
    ) -> Sequence[APIRouter]:
        register_inspection_actions(registry, executor, policy_engine)
        register_inspection_projections()
        register_inspection_tools()
        return inspection_routers()

    def register_business_agents(self, registry) -> None:
        register_inspection_agents(registry)

    async def startup(self) -> None:
        await self._lifecycle.startup()

    async def shutdown(self) -> None:
        await self._lifecycle.shutdown()


bundle = InspectionBundle()
