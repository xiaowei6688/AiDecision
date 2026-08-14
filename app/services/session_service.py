from collections.abc import AsyncIterator, Sequence
from collections.abc import Callable
import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.types import Command

from app.agents.state import default_dst_metadata
from app.services.context_compressor import ContextCompressor
from app.schemas.chat import HumanResumeRequest, SessionStateResponse
from app.core.runtime_context import RequestRuntimeContext, reset_runtime_context, set_runtime_context
from app.integrations.projections import project_human_interrupt


class SessionService:
    """将FastAPI会话连接到deepagents线程."""

    def __init__(
        self,
        agent: Any,
        context_compressor: ContextCompressor | None = None,
        runtime_context_provider: Callable[[str], RequestRuntimeContext] | None = None,
    ) -> None:
        self._agent = agent
        self._context_compressor = context_compressor
        self._runtime_context_provider = runtime_context_provider

    def _config(self, session_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": session_id}}

    async def send_message(
        self,
        session_id: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """向代理发送一条用户消息并返回状态."""

        await self._compress_context_if_needed(session_id)
        payload = {
            "messages": [HumanMessage(content=message)],
            "metadata": {
                **default_dst_metadata(),
                **(metadata or {}),
            },
        }
        token = set_runtime_context(self._runtime_context(session_id))
        try:
            return await self._agent.ainvoke(payload, config=self._config(session_id))
        finally:
            reset_runtime_context(token)

    async def send_message_event(
        self,
        session_id: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送用户消息，并返回与 WebSocket 相同格式的前端事件."""

        result = await self.send_message(session_id, message, metadata)
        return self._normalize_event(session_id, result)

    async def stream_message(
        self,
        session_id: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """用户消息的流式输出."""

        await self._compress_context_if_needed(session_id)
        payload = {
            "messages": [HumanMessage(content=message)],
            "metadata": {
                **default_dst_metadata(),
                **(metadata or {}),
            },
        }
        token = set_runtime_context(self._runtime_context(session_id))
        try:
            async for event in self._agent.astream(
                payload, config=self._config(session_id), stream_mode="updates"
            ):
                yield self._normalize_event(session_id, event)
        finally:
            reset_runtime_context(token)

    async def resume(
        self,
        session_id: str,
        request: HumanResumeRequest,
    ) -> dict[str, Any]:
        """恢复由人机交互中断暂停的图."""

        result = await self._resume(session_id, request)
        return self._jsonable(result)

    async def resume_event(
        self,
        session_id: str,
        request: HumanResumeRequest,
    ) -> dict[str, Any]:
        """恢复暂停的图，并返回WebSocket友好的事件."""

        result = await self._resume(session_id, request)
        return self._normalize_event(session_id, result)

    async def _resume(
        self,
        session_id: str,
        request: HumanResumeRequest,
    ) -> dict[str, Any]:
        resume_payload = {
            "action": request.action,
            "content": request.content,
            "data": request.data,
        }
        token = set_runtime_context(self._runtime_context(session_id))
        try:
            return await self._agent.ainvoke(Command(resume=resume_payload), config=self._config(session_id))
        finally:
            reset_runtime_context(token)

    def _runtime_context(self, session_id: str) -> RequestRuntimeContext:
        if self._runtime_context_provider is not None:
            context = self._runtime_context_provider(session_id)
            return RequestRuntimeContext(
                user_id=context.user_id,
                user_roles=context.user_roles,
                session_id=session_id,
                metadata=context.metadata,
            )
        return RequestRuntimeContext(session_id=session_id)

    async def get_state(self, session_id: str) -> SessionStateResponse:
        """返回最新的DST状态的紧凑可序列化视图."""

        snapshot = await self._agent.aget_state(self._config(session_id))
        values = dict(snapshot.values or {})
        exists = bool(values)
        pending = values.get("pending_human_action")

        return SessionStateResponse(
            session_id=session_id,
            exists=exists,
            intent=values.get("intent"),
            dialogue_stage=self._stringify(values.get("dialogue_stage")),
            summary=values.get("summary"),
            pending_human_action=pending if isinstance(pending, dict) else None,
            domain_state=values.get("domain_state") if isinstance(values.get("domain_state"), dict) else {},
            last_active_agent=values.get("last_active_agent"),
            metadata=values.get("metadata") or {},
        )

    async def get_session_history(self, session_id: str) -> list[dict[str, Any]]:
        """Return checkpoint messages in the legacy chat-history shape."""

        snapshot = await self._agent.aget_state(self._config(session_id))
        values = dict(snapshot.values or {})
        messages = values.get("messages")
        if not isinstance(messages, Sequence) or isinstance(messages, str | bytes):
            return []
        history: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, BaseMessage):
                continue
            history.append({
                "type": message.type,
                "role": "assistant" if isinstance(message, AIMessage) else "user",
                "content": self._message_content_to_text(message.content),
            })
        return history

    async def _compress_context_if_needed(self, session_id: str) -> None:
        if self._context_compressor is None:
            return

        snapshot = await self._agent.aget_state(self._config(session_id))
        values = dict(snapshot.values or {})
        if not values:
            return

        result = self._context_compressor.compress(values)
        if result.update:
            await self._agent.aupdate_state(
                self._config(session_id),
                result.update,
            )

    def _normalize_event(self, session_id: str, event: Any) -> dict[str, Any]:
        """将LangGraph流事件转换为前端友好的字典."""

        if isinstance(event, dict) and "__interrupt__" in event:
            interrupts = self._jsonable(event["__interrupt__"])
            projected = project_human_interrupt(interrupts if isinstance(interrupts, list) else [interrupts])
            payload = {
                "type": "human_action_required",
                "session_id": session_id,
                "data": {"interrupts": interrupts},
            }
            payload.update(projected)
            return payload

        confirmation_interrupt = self._confirmation_interrupt_from_event(event)
        if confirmation_interrupt is not None:
            projected = project_human_interrupt([confirmation_interrupt])
            payload = {
                "type": "human_action_required",
                "session_id": session_id,
                "content": confirmation_interrupt.get("question"),
                "data": {"interrupts": [confirmation_interrupt]},
            }
            payload.update(projected)
            return payload

        text = self._extract_latest_ai_text(event)
        if text:
            return {
                "type": "message",
                "session_id": session_id,
                "content": text,
                "data": self._jsonable(event),
            }

        return {
            "type": "dst_state",
            "session_id": session_id,
            "data": self._jsonable(event),
        }

    def _extract_latest_ai_text(self, event: Any) -> str | None:
        if not isinstance(event, dict):
            return None

        for messages in self._message_sequences(event):
            if not messages:
                continue
            latest = messages[-1]
            if isinstance(latest, AIMessage):
                return self._message_content_to_text(latest.content)

        return None

    def _message_sequences(self, event: dict[str, Any]) -> list[Sequence[Any]]:
        candidates = [event.get("messages")]
        candidates.extend(
            value.get("messages")
            for value in event.values()
            if isinstance(value, dict)
        )

        sequences: list[Sequence[Any]] = []
        for candidate in candidates:
            messages = self._unwrap_langgraph_value(candidate)
            if isinstance(messages, Sequence) and not isinstance(messages, str | bytes):
                sequences.append(messages)
        return sequences

    def _message_content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item, str):
                    parts.append(item)
            return "\n".join(parts)
        return str(content)

    def _confirmation_interrupt_from_event(self, event: Any) -> dict[str, Any] | None:
        for candidate in self._candidate_dicts(event):
            if candidate.get("status") != "requires_confirmation":
                continue
            payload = self._confirmation_payload(candidate)
            if not payload:
                continue
            return {
                "question": candidate.get("question") or candidate.get("message") or "请确认是否继续",
                "allowed_actions": ["approve", "reject", "edit"],
                "recommended_action": "approve",
                "ui_type": "confirmation",
                "payload": payload,
            }
        return None

    def _confirmation_payload(self, candidate: dict[str, Any]) -> dict[str, Any]:
        data = candidate.get("data")
        data = data if isinstance(data, dict) else {}
        payload = {
            key: value
            for key, value in candidate.items()
            if key not in {"status", "message", "data", "error_code"}
        }
        if "confirmation_token" in data:
            payload["confirmation_token"] = data["confirmation_token"]
        if "params" in data:
            payload["params"] = data["params"]
        return payload

    def _candidate_dicts(self, value: Any) -> list[dict[str, Any]]:
        value = self._unwrap_langgraph_value(value)
        if isinstance(value, BaseMessage):
            content = self._message_content_to_text(value.content)
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                return []
            return self._candidate_dicts(parsed)
        if isinstance(value, dict):
            candidates = [value]
            for item in value.values():
                candidates.extend(self._candidate_dicts(item))
            return candidates
        if isinstance(value, list | tuple):
            candidates: list[dict[str, Any]] = []
            for item in value:
                candidates.extend(self._candidate_dicts(item))
            return candidates
        return []

    def _jsonable(self, value: Any) -> Any:
        unwrapped = self._unwrap_langgraph_value(value)
        if unwrapped is not value:
            return self._jsonable(unwrapped)
        if isinstance(value, BaseMessage):
            return {
                "type": value.type,
                "content": self._message_content_to_text(value.content),
            }
        if isinstance(value, dict):
            return {str(key): self._jsonable(item) for key, item in value.items()}
        if isinstance(value, list | tuple):
            return [self._jsonable(item) for item in value]
        return self._stringify(value)

    def _unwrap_langgraph_value(self, value: Any) -> Any:
        if value.__class__.__name__ == "Overwrite" and hasattr(value, "value"):
            return value.value
        return value

    def _stringify(self, value: Any) -> Any:
        if hasattr(value, "value"):
            return value.value
        return value
