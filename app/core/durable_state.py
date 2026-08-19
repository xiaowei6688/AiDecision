from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from typing import Any, AsyncIterator

from psycopg_pool import AsyncConnectionPool

logger = logging.getLogger(__name__)


_TABLE_DEFINITIONS = {
    "agent_sessions": """
        CREATE TABLE agent_sessions (
            session_id TEXT PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """,
    "agent_confirmation_tokens": """
        CREATE TABLE agent_confirmation_tokens (
            token TEXT PRIMARY KEY,
            expires_at BIGINT NOT NULL,
            consumed_at BIGINT
        )
    """,
    "agent_execution_plans": """
        CREATE TABLE agent_execution_plans (
            plan_id TEXT PRIMARY KEY,
            session_id TEXT,
            plan JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """,
    "agent_action_idempotency": """
        CREATE TABLE agent_action_idempotency (
            idempotency_key TEXT PRIMARY KEY,
            result JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """,
}


class PostgresDurableState:
    """多实例运行时的会话、一次性确认和执行状态。"""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    @asynccontextmanager
    async def _cursor(self) -> AsyncIterator[Any]:
        async with self._pool.connection() as connection:
            async with connection.cursor() as cursor:
                yield cursor

    async def setup(self) -> None:
        """启动时检查并创建运行时状态表，不修改既有业务数据。"""

        created: list[str] = []
        async with self._cursor() as cursor:
            for table_name, statement in _TABLE_DEFINITIONS.items():
                await cursor.execute("SELECT to_regclass(%s)", (table_name,))
                exists = await cursor.fetchone()
                if exists is None or exists[0] is None:
                    await cursor.execute(statement)
                    created.append(table_name)

            # 保留旧版本的会话入口，迁移只复制 session_id，不删除历史表或消息。
            await cursor.execute(
                """
                DO $$
                BEGIN
                    IF to_regclass('agent_session_owners') IS NOT NULL THEN
                        INSERT INTO agent_sessions(session_id)
                        SELECT session_id FROM agent_session_owners
                        ON CONFLICT DO NOTHING;
                    END IF;
                END $$
                """
            )
        if created:
            logger.info("运行时状态表不存在，已创建: %s", ", ".join(created))
        else:
            logger.info("运行时状态表检查完成，全部已存在")

    async def create_session(self, session_id: str) -> None:
        async with self._cursor() as cursor:
            await cursor.execute(
                "INSERT INTO agent_sessions(session_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (session_id,),
            )

    async def session_exists(self, session_id: str) -> bool:
        async with self._cursor() as cursor:
            await cursor.execute(
                "SELECT 1 FROM agent_sessions WHERE session_id = %s",
                (session_id,),
            )
            record = await cursor.fetchone()
        return record is not None

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
