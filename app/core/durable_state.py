from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, cast

from psycopg_pool import AsyncConnectionPool

from app.core.auth import AuthContext
from app.core.runtime_context import RequestRuntimeContext


class PostgresDurableState:
    """Durable ownership and single-use confirmation state for multi-instance runs."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    @asynccontextmanager
    async def _cursor(self) -> AsyncIterator[Any]:
        async with self._pool.connection() as connection:
            async with connection.cursor() as cursor:
                yield cursor

    async def setup(self) -> None:
        async with self._cursor() as cursor:
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_session_owners (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    roles TEXT[] NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS agent_confirmation_tokens (
                    token TEXT PRIMARY KEY,
                    expires_at BIGINT NOT NULL,
                    consumed_at BIGINT
                );
                CREATE TABLE IF NOT EXISTS agent_execution_plans (
                    plan_id TEXT PRIMARY KEY,
                    session_id TEXT,
                    plan JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                CREATE TABLE IF NOT EXISTS agent_action_idempotency (
                    idempotency_key TEXT PRIMARY KEY,
                    result JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )

    async def create_session(self, session_id: str, auth: AuthContext) -> None:
        async with self._cursor() as cursor:
            await cursor.execute(
                """INSERT INTO agent_session_owners(session_id, user_id, tenant_id, roles)
                VALUES (%s, %s, %s, %s)""",
                (session_id, auth.user_id, auth.tenant_id, list(auth.roles)),
            )

    async def session_context(self, session_id: str, auth: AuthContext) -> RequestRuntimeContext:
        async with self._cursor() as cursor:
            await cursor.execute(
                "SELECT user_id, tenant_id, roles FROM agent_session_owners WHERE session_id = %s",
                (session_id,),
            )
            record = await cursor.fetchone()
        owner = cast(tuple[str, str, list[str]] | None, record)
        if owner is None or owner[0] != auth.user_id or owner[1] != auth.tenant_id:
            raise PermissionError("Session does not belong to the authenticated principal")
        return RequestRuntimeContext(
            user_id=owner[0], user_roles=tuple(owner[2]), session_id=session_id,
            metadata={"tenant_id": owner[1]},
        )

    async def issue_confirmation(self, token: str, expires_at: int) -> None:
        async with self._cursor() as cursor:
            await cursor.execute(
                "INSERT INTO agent_confirmation_tokens(token, expires_at) VALUES (%s, %s)",
                (token, expires_at),
            )

    async def consume_confirmation(self, token: str, now: int) -> bool:
        async with self._cursor() as cursor:
            await cursor.execute(
                """UPDATE agent_confirmation_tokens SET consumed_at = %s
                WHERE token = %s AND consumed_at IS NULL AND expires_at >= %s
                RETURNING token""",
                (now, token, now),
            )
            consumed = await cursor.fetchone()
        return consumed is not None

    async def save_plan(self, plan_id: str, session_id: str | None, payload: str) -> None:
        async with self._cursor() as cursor:
            await cursor.execute(
                """INSERT INTO agent_execution_plans(plan_id, session_id, plan, updated_at)
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (plan_id) DO UPDATE SET
                    session_id = EXCLUDED.session_id,
                    plan = EXCLUDED.plan,
                    updated_at = NOW()""",
                (plan_id, session_id, payload),
            )

    async def load_plan(self, plan_id: str, session_id: str | None) -> str:
        async with self._cursor() as cursor:
            await cursor.execute(
                "SELECT session_id, plan FROM agent_execution_plans WHERE plan_id = %s",
                (plan_id,),
            )
            record = await cursor.fetchone()
        if record is None:
            raise KeyError(f"Unknown execution plan: {plan_id}")
        owner_session, payload = cast(tuple[str | None, object], record)
        if owner_session != session_id:
            raise PermissionError("Execution plan does not belong to the current session")
        if isinstance(payload, str):
            return payload
        import json
        return json.dumps(payload, ensure_ascii=False, default=str)

    async def load_idempotent_result(self, idempotency_key: str) -> str | None:
        async with self._cursor() as cursor:
            await cursor.execute(
                "SELECT result FROM agent_action_idempotency WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            record = await cursor.fetchone()
        if record is None:
            return None
        payload = cast(tuple[object], record)[0]
        if isinstance(payload, str):
            return payload
        import json
        return json.dumps(payload, ensure_ascii=False, default=str)

    async def save_idempotent_result(self, idempotency_key: str, payload: str) -> None:
        async with self._cursor() as cursor:
            await cursor.execute(
                """INSERT INTO agent_action_idempotency(idempotency_key, result)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (idempotency_key) DO NOTHING""",
                (idempotency_key, payload),
            )


@asynccontextmanager
async def create_postgres_durable_state(database_url: str) -> AsyncIterator[PostgresDurableState]:
    pool = AsyncConnectionPool(
        database_url,
        kwargs={"autocommit": True},
        min_size=1,
        max_size=10,
        open=False,
        check=AsyncConnectionPool.check_connection,
    )
    async with pool:
        state = PostgresDurableState(pool)
        await state.setup()
        yield state
