from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_auth_context, get_session_access, get_session_service, get_settings_from_app
from app.core.auth import AuthContext
from app.core.session_access import SessionAccessStore
from app.core.config import Settings
from app.schemas.chat import (
    ChatRequest,
    CreateSessionResponse,
    HumanResumeRequest,
    InteractionResponse,
    ListSessionsResponse,
    SessionHistoryResponse,
    SessionRecord,
    SessionStateResponse,
)
from app.services.session_service import SessionService

router = APIRouter()


async def _ensure_access(access: SessionAccessStore, session_id: str, auth: AuthContext) -> None:
    try:
        await access.ensure_access(session_id, auth)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/health")
async def health(settings: Settings = Depends(get_settings_from_app)) -> dict[str, str]:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.environment,
    }


@router.get("/sessions", response_model=ListSessionsResponse)
async def list_sessions(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
    session_service: SessionService = Depends(get_session_service),
) -> ListSessionsResponse:
    session_ids = access.list_owned(auth)[offset : offset + limit]
    records: list[SessionRecord] = []
    for session_id in session_ids:
        state = await session_service.get_state(session_id)
        records.append(SessionRecord(
            session_id=session_id,
            intent=state.intent,
            dialogue_stage=state.dialogue_stage,
            summary=state.summary,
        ))
    return ListSessionsResponse(sessions=records, total=len(session_ids))


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
) -> CreateSessionResponse:
    """为前端创建服务器拥有的会话id."""

    session_id = str(uuid4())
    await access.create(session_id, auth)
    return CreateSessionResponse(session_id=session_id)


@router.post("/sessions/{session_id}/refresh", response_model=CreateSessionResponse)
async def refresh_session(
    session_id: str,
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
) -> CreateSessionResponse:
    await _ensure_access(access, session_id, auth)
    refreshed_id = str(uuid4())
    await access.create(refreshed_id, auth)
    return CreateSessionResponse(session_id=refreshed_id)


@router.get("/sessions/{session_id}/state", response_model=SessionStateResponse)
async def get_session_state(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
) -> SessionStateResponse:
    await _ensure_access(access, session_id, auth)
    return await session_service.get_state(session_id)


@router.get("/sessions/{session_id}/history", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
) -> SessionHistoryResponse:
    await _ensure_access(access, session_id, auth)
    history = await session_service.get_session_history(session_id)
    return SessionHistoryResponse(session_id=session_id, exists=bool(history), history=history)


@router.post("/sessions/{session_id}/messages", response_model=InteractionResponse)
async def send_session_message(
    session_id: str,
    request: ChatRequest | None = None,
    message: str | None = Query(default=None),
    session_service: SessionService = Depends(get_session_service),
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
) -> InteractionResponse:
    """返回正常或HITL事件的HTTP聊天端点."""

    await _ensure_access(access, session_id, auth)
    content = request.message if request is not None else message
    if not content:
        raise HTTPException(status_code=422, detail="message is required")
    event = await session_service.send_message_event(
        session_id=session_id,
        message=content,
        metadata=request.metadata if request is not None else {},
    )
    state = await session_service.get_state(session_id)
    return InteractionResponse(event=event, state=state)


@router.post("/sessions/{session_id}/resume")
async def resume_session(
    session_id: str,
    request: HumanResumeRequest,
    session_service: SessionService = Depends(get_session_service),
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
) -> InteractionResponse:
    await _ensure_access(access, session_id, auth)
    event = await session_service.resume_event(session_id, request)
    state = await session_service.get_state(session_id)
    return InteractionResponse(event=event, state=state)
