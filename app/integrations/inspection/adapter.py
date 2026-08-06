from typing import Any

from app.actions.schemas import ActionExecutionContext


ADAPTER_NAME = "inspection"


class InspectionAdapter:
    """Adapter for the inspection system.

    Replace the demo return values with real HTTP/RPC/MCP calls when the
    inspection backend is ready.
    """

    async def invoke(
        self,
        method: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        if method == "create_task":
            return {
                "task_id": "INS-DEMO-001",
                "device_id": params["device_id"],
                "assignee_id": params["assignee_id"],
                "due_time": params["due_time"],
            }
        raise ValueError(f"Unsupported inspection method: {method}")
