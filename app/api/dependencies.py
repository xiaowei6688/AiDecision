from fastapi import Request

from app.core.config import Settings
from app.services.session_service import SessionService
from app.core.auth import AuthContext, authenticate_request
from app.core.session_access import SessionAccessStore


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_session_service(request: Request) -> SessionService:
    return request.app.state.session_service


def get_auth_context(request: Request) -> AuthContext:
    return authenticate_request(request, request.app.state.settings)


def get_session_access(request: Request) -> SessionAccessStore:
    return request.app.state.session_access
