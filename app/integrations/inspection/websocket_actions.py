"""Inspection-owned WebSocket action-result handlers."""

from __future__ import annotations

from typing import Any

from app.schemas.chat import HumanResumeRequest, WebSocketClientEvent


WORK_ORDER_ACTION_CODES = {"createTempOrder", "inspection.create_work_order", "create_work_order"}


def inspection_work_order_action_result_to_resume(
    client_event: WebSocketClientEvent,
) -> HumanResumeRequest | None:
    action_result = client_event.action_result or {}
    action_code = _action_code(client_event, action_result)
    if action_code not in WORK_ORDER_ACTION_CODES:
        return None

    success = bool(action_result.get("success", action_result.get("status") == "success"))
    return HumanResumeRequest(
        action="approve" if success else "reject",
        content=action_result.get("message") or client_event.content,
        data={
            **action_result,
            "actionCode": "createTempOrder",
        },
    )


def _action_code(client_event: WebSocketClientEvent, action_result: dict[str, Any]) -> str | None:
    value = client_event.action_code or action_result.get("actionCode") or action_result.get("action_code")
    return str(value) if value not in (None, "") else None
