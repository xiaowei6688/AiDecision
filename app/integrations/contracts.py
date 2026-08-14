"""Generic plugin contracts for business integrations.

An integration bundle is the framework's plugin boundary.  Business code may
register capabilities here, but the core runtime only sees registries and
protocol-compatible callbacks.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from fastapi import APIRouter

from app.integrations.context import PluginContext


class PluginBundle(Protocol):
    """Primary contract implemented by every business plugin."""

    name: str

    def register_context(self, context: PluginContext) -> Sequence[APIRouter]:
        """Register all capabilities into one application-scoped context."""

    async def startup(self) -> None:
        ...

    async def shutdown(self) -> None:
        ...
