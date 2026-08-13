"""Inspection integration HTTP entrypoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.integrations.inspection.notifications import (
    InspectionNotificationRequest,
    build_notification_event,
)


router = APIRouter(prefix="/integrations/inspection", tags=["inspection"])


@router.post("/notify")
async def notify_inspection(request: InspectionNotificationRequest) -> dict[str, object]:
    try:
        return build_notification_event(request)
    except Exception as exc:  # pragma: no cover - defensive boundary
        raise HTTPException(status_code=500, detail=f"处理失败: {exc}") from exc
