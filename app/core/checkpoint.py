from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings


class CheckpointConfigurationError(RuntimeError):
    """当持久DST存储配置不正确时引发."""


@asynccontextmanager
async def create_postgres_checkpointer(
    settings: Settings,
) -> AsyncIterator[BaseCheckpointSaver]:
    """创建一个PostgreSQL支持的LangGraph检查指针。
    DeepAgents使用LangGraph的`thread_id `作为持久会话密钥。
    在PostgreSQL中保留该检查点是DST状态跟踪器的核心持久化机制。
    """

    if not settings.database_url:
        raise CheckpointConfigurationError(
            "DATABASE_URL 是必需的, 选择PostgreSQL作为DST持久化存储。"
        )

    async with AsyncPostgresSaver.from_conn_string(settings.database_url) as saver:
        if settings.checkpoint_setup_on_start:
            await saver.setup()
        yield saver
