from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.main_agent import build_main_agent
from app.actions.executor import default_action_executor
from app.api.routes import router as http_router
from app.api.websocket import router as websocket_router
from app.integrations.bootstrap import IntegrationManager
from app.core.checkpoint import create_postgres_checkpointer
from app.core.durable_state import create_postgres_durable_state
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.context_compressor import ContextCompressor
from app.services.session_service import SessionService
from app.domain.plan_store import default_plan_store


def create_app(
    settings: Settings | None = None,
    session_service: SessionService | None = None,
) -> FastAPI:
    """创建FastAPI应用.

    测试可能注入一个假的SessionService. 生产启动构建deepagents图与PostgreSQL检查指针.
    """

    runtime_settings = settings or get_settings()
    integration_manager = IntegrationManager(runtime_settings.enabled_integrations)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(runtime_settings.log_level)
        app.state.settings = runtime_settings
        default_action_executor.configure_confirmation(
            runtime_settings.confirmation_secret.get_secret_value(),
            runtime_settings.confirmation_ttl_seconds,
        )
        await integration_manager.startup()

        try:
            if session_service is not None:
                app.state.session_service = session_service
                yield
                return

            async with create_postgres_checkpointer(runtime_settings) as checkpointer:
                async with create_postgres_durable_state(runtime_settings.database_url or "") as durable_state:
                    app.state.session_access = SessionAccessStore(durable_state=durable_state)
                    default_action_executor.set_durable_state(durable_state)
                    default_plan_store.set_durable_state(durable_state)
                    context_compressor = ContextCompressor(
                        recent_messages=runtime_settings.context_recent_messages,
                        summary_max_chars=runtime_settings.context_summary_max_chars,
                    )
                    agent = build_main_agent(runtime_settings, checkpointer)
                    app.state.session_service = SessionService(
                        agent,
                        context_compressor,
                        runtime_context_provider=app.state.session_access.context,
                    )
                    yield
                    default_action_executor.set_durable_state(None)
                    default_plan_store.set_durable_state(None)
        finally:
            await integration_manager.shutdown()

    app = FastAPI(title=runtime_settings.app_name, lifespan=lifespan)
    from app.core.session_access import SessionAccessStore
    app.state.session_access = SessionAccessStore(
        allow_unknown=runtime_settings.environment == "development"
    )
    app.state.settings = runtime_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(http_router)
    app.include_router(websocket_router)
    from app.actions.policy import default_policy_engine
    from app.actions.registry import default_action_registry

    for router in integration_manager.register_integrations(
        default_action_registry,
        default_action_executor,
        default_policy_engine,
    ):
        app.include_router(router)
    return app


app = create_app()
