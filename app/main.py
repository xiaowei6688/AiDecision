from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.main_agent import build_main_agent
from app.api.routes import router as http_router
from app.api.websocket import router as websocket_router
from app.core.checkpoint import create_postgres_checkpointer
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.context_compressor import ContextCompressor
from app.services.session_service import SessionService


def create_app(
    settings: Settings | None = None,
    session_service: SessionService | None = None,
) -> FastAPI:
    """创建FastAPI应用.

    测试可能注入一个假的SessionService. 生产启动构建deepagents图与PostgreSQL检查指针.
    """

    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(runtime_settings.log_level)
        app.state.settings = runtime_settings

        if session_service is not None:
            app.state.session_service = session_service
            yield
            return

        async with create_postgres_checkpointer(runtime_settings) as checkpointer:
            agent = build_main_agent(runtime_settings, checkpointer)
            context_compressor = ContextCompressor(
                recent_messages=runtime_settings.context_recent_messages,
                summary_max_chars=runtime_settings.context_summary_max_chars,
            )
            app.state.session_service = SessionService(agent, context_compressor)
            yield

    app = FastAPI(title=runtime_settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(http_router)
    app.include_router(websocket_router)
    return app


app = create_app()
