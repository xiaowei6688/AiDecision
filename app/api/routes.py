import json
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import get_auth_context, get_session_access, get_session_service, get_settings_from_app
from app.core.auth import AuthContext
from app.core.session_access import SessionAccessStore
from app.core.config import Settings
from app.schemas.chat import (
    ChatRequest,
    CreateSessionResponse,
    HumanResumeRequest,
    InteractionResponse,
    LegacyChatRequest,
    ListSessionsResponse,
    SessionHistoryResponse,
    SessionHistorySearchHit,
    SessionHistorySearchResponse,
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
@router.get("/history/{session_id}", response_model=SessionHistoryResponse)
async def get_session_history(
    session_id: str,
    q: str | None = Query(default=None, min_length=1),
    role: str | None = Query(default=None),
    message_type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    session_service: SessionService = Depends(get_session_service),
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
) -> SessionHistoryResponse:
    await _ensure_access(access, session_id, auth)
    history = await session_service.get_session_history(
        session_id,
        query=q,
        role=role,
        message_type=message_type,
    )
    return SessionHistoryResponse(
        session_id=session_id,
        exists=bool(history),
        history=history[offset : offset + limit],
        total=len(history),
        offset=offset,
        limit=limit,
    )


@router.get("/sessions/search", response_model=SessionHistorySearchResponse)
async def search_session_history(
    q: str = Query(min_length=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=1000),
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
    session_service: SessionService = Depends(get_session_service),
) -> SessionHistorySearchResponse:
    """在当前用户拥有的会话中检索历史消息。"""

    hits: list[SessionHistorySearchHit] = []
    for session_id in access.list_owned(auth):
        messages = await session_service.get_session_history(session_id, query=q)
        if not messages:
            continue
        state = await session_service.get_state(session_id)
        hits.append(SessionHistorySearchHit(
            session_id=session_id,
            intent=state.intent,
            summary=state.summary,
            messages=messages,
        ))
    return SessionHistorySearchResponse(
        query=q,
        results=hits[offset : offset + limit],
        total=len(hits),
        offset=offset,
        limit=limit,
    )


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
    return InteractionResponse(event=_public_event(event), state=state)


@router.post("/chat", response_model=InteractionResponse)
async def legacy_chat(
    request: LegacyChatRequest,
    http_request: Request,
    session_service: SessionService = Depends(get_session_service),
    auth: AuthContext = Depends(get_auth_context),
    access: SessionAccessStore = Depends(get_session_access),
) -> InteractionResponse:
    """兼容旧版前端的单入口 HTTP 交互接口。

    旧版把 message、resume 和 actionResult 共用一个请求地址；业务回执仍由
    已启用插件转换，通用层只负责路由和会话协议归一化。
    """

    await _ensure_access(access, request.session_id, auth)
    if request.type == "message":
        content = request.content or request.message
        if not content:
            raise HTTPException(status_code=422, detail="content is required")
        event = await session_service.send_message_event(
            session_id=request.session_id,
            message=content,
            metadata=request.metadata,
        )
    elif request.type == "resume":
        if not isinstance(request.resume, dict):
            raise HTTPException(status_code=422, detail="resume is required")
        try:
            resume = HumanResumeRequest.model_validate(request.resume)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        event = await session_service.resume_event(request.session_id, resume)
    elif request.type == "actionResult":
        from app.schemas.chat import WebSocketClientEvent

        try:
            client_event = WebSocketClientEvent.model_validate(request.model_dump())
            resume = http_request.app.state.plugin_context.action_results.to_resume_request(
                client_event
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        event = await session_service.resume_event(request.session_id, resume)
        continuation = resume.data.get("businessContinuation")
        if isinstance(continuation, dict) and continuation:
            continuation_message = (
                "继续执行插件声明的单业务流程。以下 businessContinuation 已经完成业务路由。"
                "请直接继续执行插件流程，不要要求用户重复说明任务：\n"
                + json.dumps(continuation, ensure_ascii=False, separators=(",", ":"))
            )
            streamed_event = None
            async for streamed_event in session_service.stream_message(
                session_id=request.session_id,
                message=continuation_message,
                metadata={"business_continuation": continuation},
            ):
                pass
            if streamed_event is not None:
                event = streamed_event
    else:  # pragma: no cover - Pydantic enum guards this branch
        raise HTTPException(status_code=422, detail="unsupported event type")

    event["session_id"] = request.session_id
    if request.request_id is not None:
        event["request_id"] = request.request_id
    if request.message_id is not None:
        event["parent_message_id"] = request.message_id
    state = await session_service.get_state(request.session_id)
    return InteractionResponse(event=_public_event(event), state=state)


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
    return InteractionResponse(event=_public_event(event), state=state)


def _public_event(event: dict[str, Any]) -> dict[str, Any]:
    if event.get("type") == "dst_state":
        return {}
    return event
