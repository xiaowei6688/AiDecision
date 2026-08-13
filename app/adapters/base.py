from typing import Any, Protocol

from app.actions.schemas import ActionExecutionContext


class BusinessAdapter(Protocol):
    """Adapter contract for real business systems or MCP gateways."""

    async def invoke(
        self,
        method: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        """Run a named business operation and return normalized data.

        For write operations, adapters must forward context.metadata["idempotency_key"]
        to their upstream system when that system supports idempotent requests.
        """
