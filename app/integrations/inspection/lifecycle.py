"""Lifecycle hooks for inspection-owned upstream authentication."""

from __future__ import annotations

import asyncio
import logging

from app.integrations.inspection.auth import InspectionAuthClient, get_inspection_auth_client


logger = logging.getLogger(__name__)


class InspectionLifecycle:
    def __init__(self, auth_client: InspectionAuthClient | None = None) -> None:
        self._auth_client = auth_client or get_inspection_auth_client()
        self._refresh_task: asyncio.Task[None] | None = None

    async def startup(self) -> None:
        await self._prefetch_token()
        if self._auth_client.has_static_token():
            return
        if self._auth_client.missing_login_fields():
            return
        self._refresh_task = asyncio.create_task(
            self._token_refresh_loop(),
            name="inspection_allcore_token_refresh",
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

    async def _prefetch_token(self) -> None:
        missing = self._auth_client.missing_login_fields()
        if not self._auth_client.has_static_token() and missing:
            logger.info("Inspection AllCore token prefetch skipped, missing config: %s", ", ".join(missing))
            return
        try:
            await self._auth_client.allcore_auth_header()
            logger.info("Inspection AllCore token prefetch succeeded")
        except Exception as exc:
            logger.warning("Inspection AllCore token prefetch failed: %s", exc)

    async def _token_refresh_loop(self) -> None:
        interval = self._auth_client.refresh_interval_seconds()
        logger.info("Inspection AllCore token refresh task started, interval=%ss", interval)
        while True:
            try:
                await asyncio.sleep(interval)
                token = await self._auth_client.refresh()
                if token:
                    logger.info("Inspection AllCore token refreshed")
                else:
                    logger.info("Inspection AllCore token still valid, refresh skipped")
            except asyncio.CancelledError:
                logger.info("Inspection AllCore token refresh task stopped")
                raise
            except Exception as exc:
                retry_after = min(interval, 300)
                logger.warning("Inspection AllCore token refresh failed: %s, retry_after=%ss", exc, retry_after)
                await asyncio.sleep(retry_after)
