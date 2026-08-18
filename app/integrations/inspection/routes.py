"""Inspection integration HTTP entrypoints."""

from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_websocket_push_manager
from app.api.dependencies import get_session_service
from app.services.session_service import SessionService
from app.services.websocket_push import WebSocketPushManager

from app.integrations.inspection.notifications import (
    InspectionNotificationRequest,
    build_notification_event,
)
from app.integrations.inspection.bindings import inspection_session_bindings


router = APIRouter(prefix="/integrations/inspection", tags=["inspection"])


@router.post("/notify")
async def notify_inspection(
    request: InspectionNotificationRequest,
    push_manager: WebSocketPushManager = Depends(get_websocket_push_manager),
    session_service: SessionService = Depends(get_session_service),
) -> dict[str, object]:
    try:
        event = build_notification_event(request)
        session_id = event.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            session_id = inspection_session_bindings.session_for_work_order(
                request.content.workOrderId
            )
        if not isinstance(session_id, str) or not session_id:
            return {"message": "success", "type": request.type, "delivered": 0}
        event["session_id"] = session_id
        event["request_id"] = str(uuid4())
        event["message_id"] = str(uuid4())
        event["parent_message_id"] = None
        record_message = getattr(session_service, "record_assistant_message", None)
        if callable(record_message):
            latest_message = getattr(session_service, "get_latest_message_id", None)
            parent_message_id = await latest_message(session_id) if callable(latest_message) else None
            event["parent_message_id"] = parent_message_id
            await record_message(
                session_id=session_id,
                message_uuid=event["message_id"],
                request_uuid=event["request_id"],
                parent_uuid=parent_message_id,
                content=event.get("content"),
                metadata=event.get("data") or {},
                message_type="human_action_required",
            )
        delivered = await push_manager.send_to_session(session_id, event)
        return {"message": "success", "type": request.type, "delivered": delivered}
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise HTTPException(status_code=500, detail=f"处理失败: {exc}") from exc
