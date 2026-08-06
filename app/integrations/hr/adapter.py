from typing import Any

from app.actions.schemas import ActionExecutionContext


ADAPTER_NAME = "hr"


class HrAdapter:
    """Adapter for the employee management system."""

    async def invoke(
        self,
        method: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        if method == "create_leave_request":
            return {
                "leave_id": "HR-DEMO-001",
                "employee_id": params["employee_id"],
                "start_time": params["start_time"],
                "end_time": params["end_time"],
            }
        raise ValueError(f"Unsupported HR method: {method}")
