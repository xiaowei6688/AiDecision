from typing import Any

from app.actions.schemas import ActionExecutionContext


ADAPTER_NAME = "erp"


class ErpAdapter:
    """Adapter for the ERP system."""

    async def invoke(
        self,
        method: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        if method == "create_purchase_request":
            return {
                "request_id": "ERP-DEMO-001",
                "material_id": params["material_id"],
                "quantity": params["quantity"],
            }
        raise ValueError(f"Unsupported ERP method: {method}")
