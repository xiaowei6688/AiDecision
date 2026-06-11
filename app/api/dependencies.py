from fastapi import Request

from app.core.config import Settings
from app.services.session_service import SessionService


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service
