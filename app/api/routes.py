from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends

from app.api.dependencies import get_session_service, get_settings_from_app
from app.core.config import Settings
from app.schemas.chat import (
    ChatRequest,
    CreateSessionResponse,
    HumanResumeRequest,
    InteractionResponse,
    SessionStateResponse,
)
from app.services.session_service import SessionService

router = APIRouter()


@router.get("/health")
async def health(settings: Settings = Depends(get_settings_from_app)) -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session() -> CreateSessionResponse:
    """为前端创建服务器拥有的会话id."""

    return CreateSessionResponse(session_id=str(uuid4()))


@router.get("/sessions/{session_id}/state", response_model=SessionStateResponse)
async def get_session_state(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
) -> SessionStateResponse:
    return await session_service.get_state(session_id)


@router.post("/sessions/{session_id}/messages", response_model=InteractionResponse)
async def send_session_message(
    session_id: str,
    request: ChatRequest,
    session_service: SessionService = Depends(get_session_service),
) -> InteractionResponse:
    """HTTP chat endpoint that returns normal or HITL events."""

    event = await session_service.send_message_event(
        session_id=session_id,
        message=request.message,
        metadata=request.metadata,
    )
    state = await session_service.get_state(session_id)
    return InteractionResponse(event=event, state=state)


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    request: HumanResumeRequest,
    session_service: SessionService = Depends(get_session_service),
) -> InteractionResponse:
    event = await session_service.resume_event(session_id, request)
    state = await session_service.get_state(session_id)
    return InteractionResponse(event=event, state=state)
