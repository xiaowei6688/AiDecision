"""Central execution boundary for Business Agent read-only tools."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.core.progress import get_progress_channel
from app.core.runtime_context import get_runtime_context
from app.integrations.tools import IntegrationToolRegistry


@dataclass(frozen=True)
class ToolBrokerRequest:
    business_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolAuditRecord:
    request_id: str
    session_id: str | None
    user_id: str | None
    business_id: str
    tool_name: str
    title: str
    summary: str
    status: str
    duration_ms: int
    arguments: dict[str, Any]
    evidence: Any

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolBrokerResult:
    result: Any
    audit: ToolAuditRecord


class ToolBroker:
    """Authorize, execute and audit plugin-owned read-only tools."""

    def __init__(self, registry: IntegrationToolRegistry) -> None:
        self._registry = registry

    async def execute(
        self,
        request: ToolBrokerRequest,
        allowed_tool_names: tuple[str, ...],
    ) -> ToolBrokerResult:
        if request.tool_name not in allowed_tool_names:
            raise PermissionError(
                f"Business Agent {request.business_id} cannot use tool: {request.tool_name}"
            )
        tool = self._registry.read_only((request.tool_name,))[0]
        runtime = get_runtime_context()
        description = self._registry.step(request.tool_name)
        request_id = str(uuid4())
        started = perf_counter()
        progress = get_progress_channel()
        if progress is not None:
            progress.publish(
                session_id=runtime.session_id,
                source="tool_broker",
                business_id=request.business_id,
                step_id=request_id,
                title=description.title,
                summary=description.summary,
                status="running",
                data={
                    "businessId": request.business_id,
                    "toolName": request.tool_name,
                    "source": "tool_broker",
                },
            )
        status = "success"
        try:
            result = await tool.ainvoke(request.arguments)
            if isinstance(result, dict) and (
                result.get("ok") is False
                or result.get("status") in {"failed", "error"}
            ):
                status = "failed"
        except Exception as exc:
            status = "failed"
            result = {
                "status": "failed",
                "error_code": "READONLY_TOOL_ERROR",
                "message": str(exc),
            }
        audit = ToolAuditRecord(
            request_id=request_id,
            session_id=runtime.session_id,
            user_id=runtime.user_id,
            business_id=request.business_id,
            tool_name=request.tool_name,
            title=description.title,
            summary=description.summary,
            status=status,
            duration_ms=max(0, int((perf_counter() - started) * 1000)),
            arguments=request.arguments,
            evidence=result,
        )
        if progress is not None:
            progress.publish(
                session_id=runtime.session_id,
                source="tool_broker",
                business_id=request.business_id,
                step_id=request_id,
                title=description.title,
                summary=description.summary,
                status="completed" if status == "success" else "failed",
                data={
                    "businessId": request.business_id,
                    "toolName": request.tool_name,
                    "durationMs": audit.duration_ms,
                    "source": "tool_broker",
                },
            )
        return ToolBrokerResult(result=result, audit=audit)
