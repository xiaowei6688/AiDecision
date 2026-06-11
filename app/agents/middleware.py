from collections.abc import Awaitable, Callable
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage

SUMMARY_HEADER = "以下是更早对话的压缩摘要（供参考，不要重复其中已完成的工作）："


class SummaryInjectionMiddleware(AgentMiddleware):
    """将 state 中的 `summary` 注入到 system message，确保压缩历史进入上下文。"""

    name = "summary_injection"

    def _augment(self, request: ModelRequest) -> ModelRequest:
        summary = request.state.get("summary")
        if not summary or not str(summary).strip():
            return request

        base = request.system_message
        base_text = base.text if base is not None else ""
        summary_block = f"{SUMMARY_HEADER}\n{str(summary).strip()}"
        merged = f"{base_text}\n\n{summary_block}" if base_text else summary_block

        return request.override(system_message=SystemMessage(content=merged))

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._augment(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._augment(request))
