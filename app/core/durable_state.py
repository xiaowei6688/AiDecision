from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, cast

from psycopg import AsyncConnection

from app.core.auth import AuthContext
from app.core.runtime_context import RequestRuntimeContext


class PostgresDurableState:
    """Durable ownership and single-use confirmation state for multi-instance runs."""

    def __init__(self, connection: AsyncConnection[object]) -> None:
        self._connection = connection

    async def setup(self) -> None:
        async with self._connection.cursor() as cursor:
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
                """
            )
        await self._connection.commit()

    async def create_session(self, session_id: str, auth: AuthContext) -> None:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                """INSERT INTO agent_session_owners(session_id, user_id, tenant_id, roles)
                VALUES (%s, %s, %s, %s)""",
                (session_id, auth.user_id, auth.tenant_id, list(auth.roles)),
            )
        await self._connection.commit()

    async def session_context(self, session_id: str, auth: AuthContext) -> RequestRuntimeContext:
        async with self._connection.cursor() as cursor:
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
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                "INSERT INTO agent_confirmation_tokens(token, expires_at) VALUES (%s, %s)",
                (token, expires_at),
            )
        await self._connection.commit()

    async def consume_confirmation(self, token: str, now: int) -> bool:
        async with self._connection.cursor() as cursor:
            await cursor.execute(
                """UPDATE agent_confirmation_tokens SET consumed_at = %s
                WHERE token = %s AND consumed_at IS NULL AND expires_at >= %s
                RETURNING token""",
                (now, token, now),
            )
            consumed = await cursor.fetchone()
        await self._connection.commit()
        return consumed is not None


@asynccontextmanager
async def create_postgres_durable_state(database_url: str) -> AsyncIterator[PostgresDurableState]:
    async with await AsyncConnection.connect(database_url) as connection:
        state = PostgresDurableState(connection)
        await state.setup()
        yield state
