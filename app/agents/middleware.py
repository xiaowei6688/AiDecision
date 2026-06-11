"""Agent 中间件：把压缩后的 summary 回灌进每次模型调用的上下文。

ContextCompressor 会把旧消息从 messages 中删除并合并进 state 的 `summary` 字段，
但 `summary` 只是一个 state 字段，不会自动进入模型上下文。若不回灌，压缩等同于
静默丢弃历史。该中间件在每次调用模型前，将 `summary` 追加到 system message 末尾，
使主 Agent 与子 Agent（共享同一 state）都能看到被压缩的历史。
"""

from collections.abc import Awaitable, Callable
from typing import Any

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
