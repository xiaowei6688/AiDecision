from collections.abc import Awaitable, Callable
import json
from uuid import uuid4
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.actions.schemas import ActionSpec

SUMMARY_HEADER = "以下是更早对话的压缩摘要（供参考，不要重复其中已完成的工作）："


class DirectResultMiddleware(AgentMiddleware):
    """无需再次调用模型，直接转发框架声明的工具结果。"""

    name = "direct_result"

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        direct = self._response(request)
        return direct if direct is not None else handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        direct = self._response(request)
        return direct if direct is not None else await handler(request)

    def _response(self, request: ModelRequest) -> ModelResponse | None:
        last_message = request.messages[-1] if request.messages else None
        if not isinstance(last_message, ToolMessage):
            return None
        try:
            payload = json.loads(_message_text(last_message.content))
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        framework = payload.get("_framework")
        if not isinstance(framework, dict):
            return None
        direct_action = framework.get("direct_action")
        if isinstance(direct_action, dict):
            action_id = direct_action.get("action_id")
            params = direct_action.get("params")
            if isinstance(action_id, str) and action_id and isinstance(params, dict):
                return ModelResponse(result=[AIMessage(
                    content="",
                    tool_calls=[{
                        "name": "call_business_action",
                        "args": {
                            "action_id": action_id,
                            "params": params,
                            "return_direct": True,
                        },
                        "id": f"direct_{uuid4().hex}",
                        "type": "tool_call",
                    }],
                )])
        if framework.get("return_direct") is True:
            return ModelResponse(result=[AIMessage(content="")])
        return None


class BusinessContinuationMiddleware(AgentMiddleware):
    """强制插件路由的续接流程通过其声明的业务 Agent 执行。"""

    name = "business_continuation"

    def _continuation(self, request: ModelRequest) -> dict[str, object] | None:
        metadata = request.state.get("metadata")
        continuation = (
            metadata.get("business_continuation")
            if isinstance(metadata, dict)
            else None
        )
        last_message = request.messages[-1] if request.messages else None
        if (
            not isinstance(continuation, dict)
            or not continuation
            or not isinstance(last_message, HumanMessage)
            or "businessContinuation" not in _message_text(last_message.content)
        ):
            return None
        return continuation

    def _response(self, request: ModelRequest) -> ModelResponse | None:
        if self._continuation(request) is None:
            return None
        # continuation 已由插件 actionResult 处理器完成路由。这里直接生成工具调用，
        # 不让模型从压缩历史中重新判断意图或调用内部文件工具。
        return ModelResponse(result=[AIMessage(
            content="",
            tool_calls=[{
                "name": "continue_business_workflow",
                "args": {},
                "id": f"continuation_{uuid4().hex}",
                "type": "tool_call",
            }],
        )])

    def _augment(self, request: ModelRequest) -> ModelRequest:
        if self._continuation(request) is None:
            return request

        base = request.system_message
        base_text = base.text if base is not None else ""
        correction = (
            "当前输入是插件已经完成路由的 businessContinuation。"
            "本轮第一步必须调用无参数工具 continue_business_workflow，禁止调用业务发现或协作规划工具，"
            "也禁止输出普通 assistant 消息。"
        )
        merged = f"{base_text}\n\n{correction}" if base_text else correction
        return request.override(
            system_message=SystemMessage(content=merged),
            tool_choice="continue_business_workflow",
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        direct = self._response(request)
        return direct if direct is not None else handler(self._augment(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        direct = self._response(request)
        return direct if direct is not None else await handler(self._augment(request))


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


class ConfirmationProtocolMiddleware(AgentMiddleware):
    """通过结构化动作工具重试最终文本中的动作确认。"""

    name = "confirmation_protocol"

    def __init__(self, actions: list[ActionSpec]) -> None:
        self._actions = [action for action in actions if action.confirmation.required]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        response = handler(request)
        action = self._unstructured_confirmation(response)
        if action is None:
            return response
        return handler(self._retry_request(request, action))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        response = await handler(request)
        action = self._unstructured_confirmation(response)
        if action is None:
            return response
        return await handler(self._retry_request(request, action))

    def _unstructured_confirmation(self, response: ModelResponse) -> ActionSpec | None:
        message = next(
            (item for item in reversed(response.result) if isinstance(item, AIMessage)),
            None,
        )
        if message is None or message.tool_calls:
            return None
        text = _message_text(message.content)
        if not _asks_for_confirmation(text):
            return None
        return next(
            (action for action in self._actions if _mentions_action(text, action)),
            None,
        )

    def _retry_request(self, request: ModelRequest, action: ActionSpec) -> ModelRequest:
        base = request.system_message
        base_text = base.text if base is not None else ""
        correction = (
            "协议纠正：禁止用普通 assistant 文本请求用户确认业务动作。"
            f"当前内容是在确认已注册动作 {action.action_id}（{action.title}）。"
            "如果参数已完整，必须立即调用 call_business_action，由 ActionExecutor 产生结构化"
            " human_action_required；不要另外调用 request_human_input，也不要再次输出确认文案。"
            "如果参数不完整，只用普通消息询问缺失字段，不得声称已经准备完成。"
        )
        merged = f"{base_text}\n\n{correction}" if base_text else correction
        return request.override(
            system_message=SystemMessage(content=merged),
            tool_choice="call_business_action",
        )


def _asks_for_confirmation(text: str) -> bool:
    normalized = text.lower()
    return any(marker in normalized for marker in (
        "请确认",
        "是否确认",
        "是否要",
        "是否继续",
        "回复\"是\"或\"否\"",
        "reply yes or no",
        "confirm whether",
    ))


def _mentions_action(text: str, action: ActionSpec) -> bool:
    candidates = [action.title, *action.intent_examples]
    return any(_action_phrase_matches(text, candidate) for candidate in candidates)


def _action_phrase_matches(text: str, phrase: str) -> bool:
    normalized = "".join(phrase.lower().split())
    haystack = "".join(text.lower().split())
    if normalized and normalized in haystack:
        return True
    verbs = (
        "创建", "新建", "生成", "执行", "提交", "删除", "更新", "修改",
        "发送", "支付", "审批", "启动", "停止", "取消",
    )
    for verb in verbs:
        if verb not in normalized:
            continue
        subject = normalized.replace(verb, "", 1)
        if verb in haystack and len(subject) >= 2 and subject in haystack:
            return True
    return False


def _message_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            item if isinstance(item, str) else str(item.get("text") or "")
            for item in content
            if isinstance(item, str | dict)
        )
    return str(content)
