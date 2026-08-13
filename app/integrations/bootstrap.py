from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter

from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry
from app.integrations.contracts import IntegrationBundle
from app.integrations.inspection.bundle import inspection_bundle


_BUNDLES: Sequence[IntegrationBundle] = (inspection_bundle,)


def register_integrations(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
) -> list[APIRouter]:
    """Register all enabled integration bundles and return their routers."""

    routers: list[APIRouter] = []
    for bundle in _BUNDLES:
        routers.extend(bundle.register(registry, executor, policy_engine))
    return routers


def register_business_agents(registry: BusinessAgentRegistry) -> None:
    """Register business agents supplied by integration bundles."""

    for bundle in _BUNDLES:
        register = getattr(bundle, "register_business_agents", None)
        if register is not None:
            register(registry)
