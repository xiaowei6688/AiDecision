from typing import Any, Protocol

from app.actions.schemas import ActionExecutionContext


class BusinessAdapter(Protocol):
    """真实业务系统或 MCP 网关的适配器契约。"""

    async def invoke(
        self,
        method: str,
        params: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        """执行指定的业务操作并返回标准化数据。

        执行写操作时，如果上游系统支持幂等请求，适配器必须将
        context.metadata["idempotency_key"] 转发给上游系统。
        """
