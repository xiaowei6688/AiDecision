"""WebSocket 对话接口。"""

import json
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
from app.core.auth import authenticate_websocket

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/chat")
async def new_chat_websocket(websocket: WebSocket) -> None:
    """为首次前端连接创建新的会话."""

    requested_session_id = websocket.query_params.get("session_id")
    await _chat_websocket(
        websocket,
        session_id=requested_session_id or str(uuid4()),
        created=requested_session_id is None,
    )


@router.websocket("/ws/chat/{session_id}")
async def chat_websocket(websocket: WebSocket, session_id: str) -> None:
    """AI对话."""

    await _chat_websocket(websocket, session_id=session_id, created=False)


async def _chat_websocket(websocket: WebSocket, session_id: str, created: bool) -> None:
    try:
        auth = authenticate_websocket(websocket, websocket.app.state.settings)
        access = websocket.app.state.session_access
        if created:
            await access.create(session_id, auth)
        else:
            await access.ensure_access(session_id, auth)
    except (ValueError, PermissionError) as exc:
        await websocket.close(code=1008, reason=str(exc))
        return
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

            event_session_id = client_event.session_id
            try:
                await access.ensure_access(event_session_id, auth)
            except PermissionError as exc:
                await _send_error(websocket, event_session_id, "session_not_found", str(exc))
                continue

            if client_event.type == ClientEventType.PING:
                await _send(
                    websocket,
                    WebSocketServerEvent(
                        type=ServerEventType.PONG,
                        session_id=event_session_id,
                        request_id=client_event.request_id,
                    ),
                )
                continue

            if client_event.type == ClientEventType.ACTION_RESULT:
                try:
                    resume_request = websocket.app.state.plugin_context.action_results.to_resume_request(
                        client_event
                    )
                except ValueError as exc:
                    await _send_error(websocket, event_session_id, "unsupported_action_result", str(exc))
                    continue
                event = await session_service.resume_event(event_session_id, resume_request)
                continuation = resume_request.data.get("businessContinuation")
                if isinstance(continuation, dict) and continuation:
                    async for continuation_event in session_service.stream_message(
                        session_id=event_session_id,
                        message=_business_continuation_message(continuation),
                        metadata={"business_continuation": continuation},
                    ):
                        continuation_event["request_id"] = client_event.request_id
                        continuation_event["parent_message_id"] = client_event.message_id
                        continuation_event["session_id"] = event_session_id
                        await _send_event(websocket, continuation_event)
                else:
                    event["request_id"] = client_event.request_id
                    event["parent_message_id"] = client_event.message_id
                    event["session_id"] = event_session_id
                    await _send_event(websocket, event)
                continue

            if client_event.type == ClientEventType.RESUME:
                try:
                    resume_request = HumanResumeRequest.model_validate(client_event.resume)
                except ValidationError as exc:
                    await _send_error(websocket, session_id, "invalid_resume", str(exc))
                    continue

                event = await session_service.resume_event(event_session_id, resume_request)
                event["request_id"] = client_event.request_id
                event["parent_message_id"] = client_event.message_id
                event["session_id"] = event_session_id
                await _send_event(websocket, event)
                continue

            if not client_event.content:
                await _send_error(websocket, event_session_id, "empty_message", "内容是必需的")
                continue

            async for event in session_service.stream_message(
                session_id=event_session_id,
                message=client_event.content,
                metadata=client_event.metadata,
            ):
                event["session_id"] = event_session_id
                event["request_id"] = client_event.request_id
                event["parent_message_id"] = client_event.message_id
                await _send_event(websocket, event)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session_id=%s", session_id)
    except Exception as exc:  # pragma: no cover - defensive API boundary
        logger.exception("WebSocket chat failed: session_id=%s", session_id)
        await _send_error(websocket, session_id, "server_error", str(exc))


async def _send(websocket: WebSocket, event: WebSocketServerEvent) -> None:
    await websocket.send_json(event.model_dump(mode="json"))


async def _send_event(websocket: WebSocket, event: dict[str, object]) -> None:
    if event.get("type") == ServerEventType.DST_STATE.value:
        return
    await websocket.send_json(event)


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


def _business_continuation_message(continuation: dict[str, object]) -> str:
    return (
        "继续执行插件声明的单业务流程。以下 businessContinuation 已经完成业务路由。"
        "必须直接调用无参数工具 continue_business_workflow。禁止调用 list_business_agents、"
        "plan_business_collaboration、run_business_collaboration，禁止先输出普通消息，"
        "不要要求用户重复说明任务：\n"
        + json.dumps(continuation, ensure_ascii=False, separators=(",", ":"))
    )
