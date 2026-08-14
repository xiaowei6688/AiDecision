"""Inspection integration bundle."""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter

from app.integrations.inspection.registration import (
    inspection_routers,
    register_inspection_actions,
    register_inspection_agent,
    register_inspection_projections,
    register_inspection_tools,
)
from app.integrations.inspection.lifecycle import InspectionLifecycle
from app.integrations.context import PluginContext


class InspectionBundle:
    name = "inspection"

    def __init__(self) -> None:
        self._lifecycle = InspectionLifecycle()

    def register_context(self, context: PluginContext) -> Sequence[APIRouter]:
        register_inspection_actions(context)
        register_inspection_projections(context)
        register_inspection_tools(context)
        register_inspection_agent(context)
        return inspection_routers()

    async def startup(self) -> None:
        await self._lifecycle.startup()

    async def shutdown(self) -> None:
        await self._lifecycle.shutdown()


bundle = InspectionBundle()
