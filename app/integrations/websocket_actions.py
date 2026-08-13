"""Generic WebSocket action-result translation helpers."""

from __future__ import annotations

from app.schemas.chat import HumanResumeRequest, WebSocketClientEvent


def action_result_to_resume_request(client_event: WebSocketClientEvent) -> HumanResumeRequest:
    action_result = client_event.action_result or {}
    success = bool(action_result.get("success", action_result.get("status") == "success"))
    return HumanResumeRequest(
        action="approve" if success else "reject",
        content=action_result.get("message") or client_event.content,
        data={
            **action_result,
            "actionCode": client_event.action_code,
        },
    )
