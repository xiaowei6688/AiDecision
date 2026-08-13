"""Generic integration bundle contracts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from fastapi import APIRouter

from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry


class IntegrationBundle(Protocol):
    name: str

    def register(
        self,
        registry: ActionRegistry,
        executor: BusinessActionExecutor,
        policy_engine: PolicyEngine,
    ) -> Sequence[APIRouter]:
        ...

    def register_business_agents(self, registry: Any) -> None:
        ...
