from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Iterable

from fastapi import APIRouter

from app.integrations.contracts import PluginBundle
from app.integrations.context import PluginContext


class IntegrationManager:
    """在应用边界发现并启用业务插件。"""
    def __init__(self, enabled_integrations: list[str] | None = None) -> None:
        self._enabled = {
            name.strip()
            for name in (enabled_integrations or [])
            if isinstance(name, str) and name.strip()
        }

    def register_context(self, context: PluginContext) -> list[APIRouter]:
        """将所有已启用的插件能力注册到同一个应用上下文。"""

        routers: list[APIRouter] = []
        for bundle in self._discover_enabled_bundles():
            routers.extend(bundle.register_context(context))
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
            if "*" not in self._enabled and bundle.name not in self._enabled:
                continue
            yield bundle

    def _discover_bundles(self) -> Iterable[PluginBundle]:
        package = importlib.import_module("app.integrations")
        for module_info in pkgutil.iter_modules(package.__path__):
            if module_info.name in {"bootstrap", "contracts", "__pycache__"}:
                continue
            bundle_module_name = f"{package.__name__}.{module_info.name}.bundle"
            try:
                bundle_module = importlib.import_module(bundle_module_name)
            except ModuleNotFoundError as exc:
                if exc.name != bundle_module_name:
                    raise
                continue
            bundle = getattr(bundle_module, "bundle", None)
            if bundle is not None:
                yield bundle
