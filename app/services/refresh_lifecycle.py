"""可复用的启动预取与定期刷新生命周期。"""

from __future__ import annotations

import asyncio
import logging
from typing import Protocol


logger = logging.getLogger(__name__)


class RefreshableResource(Protocol):
    name: str

    def is_configured(self) -> bool:
        ...

    def background_refresh_enabled(self) -> bool:
        ...

    def refresh_interval_seconds(self) -> int:
        ...

    async def prefetch(self) -> object:
        ...

    async def refresh(self) -> object:
        ...


class RefreshLifecycle:
    """预取指定资源，并在后台持续刷新。"""

    def __init__(self, resource: RefreshableResource) -> None:
        self._resource = resource
        self._refresh_task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        if not self._resource.is_configured():
            logger.info("%s startup prefetch skipped: not configured", self._resource.name)
            return
        try:
            await self._resource.prefetch()
        except Exception as exc:
            logger.warning("%s startup prefetch failed: %s", self._resource.name, exc)
            return
        logger.info("%s startup prefetch succeeded", self._resource.name)
        if self._resource.background_refresh_enabled():
            self._refresh_task = asyncio.create_task(
                self._refresh_loop(),
                name=f"{self._resource.name.lower().replace(' ', '_')}_refresh",
            )

    async def shutdown(self) -> None:
        if self._refresh_task is None:
            return
        self._refresh_task.cancel()
        try:
            await self._refresh_task
        except asyncio.CancelledError:
            pass
        self._refresh_task = None

    async def _refresh_loop(self) -> None:
        interval = self._resource.refresh_interval_seconds()
        logger.info(
            "%s background refresh started, interval=%ss",
            self._resource.name,
            interval,
        )
        while True:
            try:
                await asyncio.sleep(interval)
                await self._resource.refresh()
                logger.info("%s background refresh succeeded", self._resource.name)
            except asyncio.CancelledError:
                logger.info("%s background refresh stopped", self._resource.name)
                raise
            except Exception as exc:
                retry_after = min(interval, 300)
                logger.warning(
                    "%s background refresh failed: %s; retrying in %ss",
                    self._resource.name,
                    exc,
                    retry_after,
                )
                await asyncio.sleep(retry_after)
