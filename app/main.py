from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.main_agent import build_main_agent
from app.api.routes import router as http_router
from app.api.websocket import router as websocket_router
from app.integrations.bootstrap import IntegrationManager
from app.core.checkpoint import create_postgres_checkpointer
from app.core.durable_state import create_postgres_durable_state
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.services.context_compressor import ContextCompressor
from app.services.session_service import SessionService
from app.services.websocket_push import WebSocketPushManager
from app.domain.plan_store import default_plan_store
from app.integrations.context import PluginContext


def create_app(
    settings: Settings | None = None,
    session_service: SessionService | None = None,
) -> FastAPI:
    """创建FastAPI应用.

    测试可能注入一个假的SessionService. 生产启动构建deepagents图与PostgreSQL检查指针.
    """

    runtime_settings = settings or get_settings()
    integration_manager = IntegrationManager(runtime_settings.enabled_integrations)
    plugin_context = PluginContext()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(runtime_settings.log_level)
        app.state.settings = runtime_settings
        plugin_context.action_executor.configure_confirmation(
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
                    app.state.session_access = SessionRegistry(durable_state=durable_state)
                    plugin_context.action_executor.set_durable_state(durable_state)
                    default_plan_store.set_durable_state(durable_state)
                    context_compressor = ContextCompressor(
                        recent_messages=runtime_settings.context_recent_messages,
                        summary_max_chars=runtime_settings.context_summary_max_chars,
                    )
                    agent = build_main_agent(
                        runtime_settings, checkpointer, plugin_context
                    )
                    app.state.session_service = SessionService(
                        agent,
                        context_compressor,
                        runtime_context_provider=app.state.session_access.context,
                        plugin_context=plugin_context,
                    )
                    yield
                    plugin_context.action_executor.set_durable_state(None)
                    default_plan_store.set_durable_state(None)
        finally:
            await integration_manager.shutdown()

    app = FastAPI(title=runtime_settings.app_name, lifespan=lifespan)
    from app.core.session_access import SessionRegistry
    app.state.session_access = SessionRegistry(
        allow_unknown=runtime_settings.environment == "development"
    )
    app.state.settings = runtime_settings
    app.state.plugin_context = plugin_context
    app.state.websocket_push_manager = WebSocketPushManager()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=runtime_settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(http_router)
    app.include_router(websocket_router)
    for router in integration_manager.register_context(plugin_context):
        app.include_router(router)
    return app


app = create_app()
