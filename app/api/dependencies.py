from fastapi import Request

from app.core.config import Settings
from app.services.session_service import SessionService
from app.core.session_access import SessionRegistry
from app.services.websocket_push import WebSocketPushManager


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_session_registry(request: Request) -> SessionRegistry:
    return request.app.state.session_access


def get_websocket_push_manager(request: Request) -> WebSocketPushManager:
    return request.app.state.websocket_push_manager
