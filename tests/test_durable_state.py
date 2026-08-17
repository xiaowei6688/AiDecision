import pytest

from app.core import durable_state


@pytest.mark.asyncio
async def test_durable_state_uses_checked_autocommit_connection_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, object] = {}

    class FakePool:
        check_connection = object()

        def __init__(self, database_url: str, **kwargs: object) -> None:
            created["database_url"] = database_url
            created.update(kwargs)

        async def __aenter__(self) -> "FakePool":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    async def setup(self: durable_state.PostgresDurableState) -> None:
        created["state_pool"] = self._pool

    monkeypatch.setattr(durable_state, "AsyncConnectionPool", FakePool)
    monkeypatch.setattr(durable_state.PostgresDurableState, "setup", setup)

    async with durable_state.create_postgres_durable_state(
        "postgresql://example/db"
    ) as state:
        assert created["state_pool"] is state._pool

    assert created["database_url"] == "postgresql://example/db"
    assert created["kwargs"] == {"autocommit": True}
    assert created["min_size"] == 1
    assert created["max_size"] == 10
    assert created["open"] is False
    assert created["check"] is FakePool.check_connection
