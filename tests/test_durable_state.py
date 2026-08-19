from contextlib import asynccontextmanager

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


@pytest.mark.asyncio
async def test_durable_state_setup_creates_only_missing_tables() -> None:
    executed: list[tuple[str, tuple[object, ...] | None]] = []

    class Cursor:
        def __init__(self) -> None:
            self._table_name: str | None = None

        async def execute(self, statement: str, params: tuple[object, ...] | None = None) -> None:
            executed.append((statement, params))
            if statement == "SELECT to_regclass(%s)":
                self._table_name = str(params[0])

        async def fetchone(self) -> tuple[str | None] | None:
            return (self._table_name,) if self._table_name == "agent_sessions" else (None,)

    class State(durable_state.PostgresDurableState):
        @asynccontextmanager
        async def _cursor(self):  # type: ignore[override]
            yield Cursor()

    await State(pool=object()).setup()  # type: ignore[arg-type]

    created = [statement for statement, _ in executed if statement.lstrip().startswith("CREATE TABLE")]
    assert len(created) == 3
    assert any("DO $$" in statement for statement, _ in executed)
