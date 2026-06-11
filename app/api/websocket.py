"""WebSocket chat endpoint."""

import logging
from uuid import uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.schemas.chat import (
    ClientEventType,
    HumanResumeRequest,
    ServerEventType,
    WebSocketClientEvent,
    WebSocketServerEvent,
)
from app.services.session_service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat")
async def new_chat_websocket(websocket: WebSocket) -> None:
    """为首次前端连接创建新的会话."""

    await _chat_websocket(websocket, session_id=str(uuid4()), created=True)


@router.websocket("/ws/chat/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str) -> None:
    """AI对话."""

    await _chat_websocket(websocket, session_id=session_id, created=False)


async def _chat_websocket(websocket: WebSocket, session_id: str, created: bool) -> None:
    await websocket.accept()
    session_service: SessionService = websocket.app.state.session_service

    await _send(
        websocket,
        WebSocketServerEvent(
            type=ServerEventType.ACK,
            session_id=session_id,
            content="connected",
            data={"created": created},
        ),
    )

    try:
        while True:
            raw_payload = await websocket.receive_json()
            try:
                client_event = WebSocketClientEvent.model_validate(raw_payload)
            except ValidationError as exc:
                await _send_error(websocket, session_id, "invalid_payload", str(exc))
                continue

            if client_event.type == ClientEventType.PING:
                await _send(
                    websocket,
                    WebSocketServerEvent(
                        type=ServerEventType.PONG,
                        session_id=session_id,
                    ),
                )
                continue

            if client_event.type == ClientEventType.RESUME:
                try:
                    resume_request = HumanResumeRequest.model_validate(client_event.resume)
                except ValidationError as exc:
                    await _send_error(websocket, session_id, "invalid_resume", str(exc))
                    continue

                event = await session_service.resume_event(session_id, resume_request)
                await websocket.send_json(event)
                state = await session_service.get_state(session_id)
                await _send(
                    websocket,
                    WebSocketServerEvent(
                        type=ServerEventType.DST_STATE,
                        session_id=session_id,
                        data=state.model_dump(),
                    ),
                )
                continue

            if not client_event.content:
                await _send_error(websocket, session_id, "empty_message", "内容是必需的")
                continue

            async for event in session_service.stream_message(
                session_id=session_id,
                message=client_event.content,
                metadata=client_event.metadata,
            ):
                await websocket.send_json(event)

            state = await session_service.get_state(session_id)
            await _send(
                websocket,
                WebSocketServerEvent(
                    type=ServerEventType.DST_STATE,
                    session_id=session_id,
                    data=state.model_dump(),
                ),
            )
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session_id=%s", session_id)
    except Exception as exc:  # pragma: no cover - defensive API boundary
        logger.exception("WebSocket chat failed: session_id=%s", session_id)
        await _send_error(websocket, session_id, "server_error", str(exc))


async def _send(websocket: WebSocket, event: WebSocketServerEvent) -> None:
    await websocket.send_json(event.model_dump(mode="json"))


async def _send_error(
    websocket: WebSocket,
    session_id: str,
    code: str,
    message: str,
) -> None:
    await _send(
        websocket,
        WebSocketServerEvent(
            type=ServerEventType.ERROR,
            session_id=session_id,
            content=message,
            data={"code": code},
        ),
    )
