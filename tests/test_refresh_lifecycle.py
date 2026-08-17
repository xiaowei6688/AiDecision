from __future__ import annotations

import asyncio

import pytest

from app.services.refresh_lifecycle import RefreshLifecycle


@pytest.mark.asyncio
async def test_refresh_lifecycle_prefetches_and_starts_background_task() -> None:
    class Resource:
        name = "Test credential"

        def __init__(self) -> None:
            self.prefetch_count = 0

        def is_configured(self) -> bool:
            return True

        def background_refresh_enabled(self) -> bool:
            return True

        def refresh_interval_seconds(self) -> int:
            return 3600

        async def prefetch(self) -> None:
            self.prefetch_count += 1

        async def refresh(self) -> None:
            return None

    resource = Resource()
    lifecycle = RefreshLifecycle(resource)

    await lifecycle.startup()
    await asyncio.sleep(0)
    await lifecycle.shutdown()

    assert resource.prefetch_count == 1


@pytest.mark.asyncio
async def test_refresh_lifecycle_skips_unconfigured_resource() -> None:
    class Resource:
        name = "Test credential"

        def is_configured(self) -> bool:
            return False

        def background_refresh_enabled(self) -> bool:
            return False

        def refresh_interval_seconds(self) -> int:
            return 3600

        async def prefetch(self) -> None:
            raise AssertionError("unconfigured resource must not be prefetched")

        async def refresh(self) -> None:
            return None

    lifecycle = RefreshLifecycle(Resource())

    await lifecycle.startup()
    await lifecycle.shutdown()
