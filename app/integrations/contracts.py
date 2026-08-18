"""业务集成使用的通用插件契约。

集成 bundle 是框架的插件边界。业务代码可以在此注册能力，但核心运行时
只能感知注册表和符合协议的回调。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from fastapi import APIRouter

from app.integrations.context import PluginContext


class PluginBundle(Protocol):
    """所有业务插件都必须实现的主契约。"""

    name: str

    def register_context(self, context: PluginContext) -> Sequence[APIRouter]:
        """将全部能力注册到同一个应用级上下文。"""

    async def startup(self) -> None:
        ...

    async def shutdown(self) -> None:
        ...
