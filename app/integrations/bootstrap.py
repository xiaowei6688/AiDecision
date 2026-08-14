from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable

from fastapi import APIRouter

from app.actions.executor import BusinessActionExecutor
from app.actions.policy import PolicyEngine
from app.actions.registry import ActionRegistry
from app.agents.business_agents import BusinessAgentRegistry
from app.integrations.contracts import IntegrationBundle, PluginBundle
from app.integrations.context import PluginContext


class IntegrationManager:
    """Discover and activate business plugins at the application boundary."""
    def __init__(self, enabled_integrations: list[str] | None = None) -> None:
        self._enabled = {name for name in (enabled_integrations or []) if name}

    def register_integrations(
        self,
        registry: ActionRegistry,
        executor: BusinessActionExecutor,
        policy_engine: PolicyEngine,
    ) -> list[APIRouter]:
        routers: list[APIRouter] = []
        for bundle in self._discover_bundles():
            if self._enabled and bundle.name not in self._enabled:
                continue
            routers.extend(bundle.register(registry, executor, policy_engine))
        return routers

    def register_business_agents(self, registry: BusinessAgentRegistry) -> None:
        for bundle in self._discover_bundles():
            if self._enabled and bundle.name not in self._enabled:
                continue
            register = getattr(bundle, "register_business_agents", None)
            if register is not None:
                register(registry)

    def register_context(self, context: PluginContext) -> list[APIRouter]:
        """Register every enabled plugin capability into one app context."""

        routers: list[APIRouter] = []
        for bundle in self._discover_enabled_bundles():
            register_context = getattr(bundle, "register_context", None)
            if register_context is not None:
                routers.extend(register_context(context))
                continue
            routers.extend(
                bundle.register(
                    context.action_registry,
                    context.action_executor,
                    context.policy_engine,
                )
            )
            register_agents = getattr(bundle, "register_business_agents", None)
            if register_agents is not None:
                register_agents(context.business_agent_registry)
        return routers

    async def startup(self) -> None:
        for bundle in self._discover_enabled_bundles():
            startup = getattr(bundle, "startup", None)
            if startup is not None:
                await startup()

    async def shutdown(self) -> None:
        for bundle in self._discover_enabled_bundles():
            shutdown = getattr(bundle, "shutdown", None)
            if shutdown is not None:
                await shutdown()

    def _discover_enabled_bundles(self) -> Iterable[PluginBundle]:
        for bundle in self._discover_bundles():
            if self._enabled and bundle.name not in self._enabled:
                continue
            yield bundle

    def _discover_bundles(self) -> Iterable[PluginBundle | IntegrationBundle]:
        package = importlib.import_module("app.integrations")
        for module_info in pkgutil.iter_modules(package.__path__):
            if module_info.name in {"bootstrap", "contracts", "__pycache__"}:
                continue
            bundle_module_name = f"{package.__name__}.{module_info.name}.bundle"
            try:
                bundle_module = importlib.import_module(bundle_module_name)
            except ModuleNotFoundError:
                continue
            bundle = getattr(bundle_module, "bundle", None)
            if bundle is not None:
                yield bundle


def register_integrations(
    registry: ActionRegistry,
    executor: BusinessActionExecutor,
    policy_engine: PolicyEngine,
    enabled_integrations: list[str] | None = None,
) -> list[APIRouter]:
    return IntegrationManager(enabled_integrations).register_integrations(
        registry, executor, policy_engine
    )


def register_business_agents(
    registry: BusinessAgentRegistry,
    enabled_integrations: list[str] | None = None,
) -> None:
    IntegrationManager(enabled_integrations).register_business_agents(registry)
