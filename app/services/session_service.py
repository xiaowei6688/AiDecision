import asyncio
from collections.abc import AsyncIterator, Sequence
from collections.abc import Callable
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.agents.state import default_dst_metadata
from app.services.context_compressor import ContextCompressor
from app.schemas.chat import HumanResumeRequest, ServerEventType, SessionStateResponse
from app.core.runtime_context import RequestRuntimeContext, reset_runtime_context, set_runtime_context
from app.core.progress import ProgressChannel, ProgressEvent, reset_progress_channel, set_progress_channel
from app.integrations.context import PluginContext


class SessionService:
    """将FastAPI会话连接到deepagents线程."""

    def __init__(
        self,
        agent: Any,
        context_compressor: ContextCompressor | None = None,
        runtime_context_provider: Callable[[str], RequestRuntimeContext] | None = None,
        plugin_context: PluginContext | None = None,
    ) -> None:
        self._agent = agent
        self._context_compressor = context_compressor
        self._runtime_context_provider = runtime_context_provider
        self._plugin_context = plugin_context or PluginContext()

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
        progress_channel = ProgressChannel()
        progress_token = set_progress_channel(progress_channel)
        seen_thinking_steps: set[tuple[str | None, str | None, str | None, str | None]] = set()
        lifecycle_statuses: set[tuple[str, str]] = set()
        active_thinking_steps: dict[str, dict[str, Any]] = {}
        pending_tool_steps: dict[str, dict[str, Any]] = {}
        public_step_ids: dict[str, str] = {}
        agent_events: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def produce_agent_events() -> None:
            try:
                async for event in self._agent.astream(
                    payload, config=self._config(session_id), stream_mode="updates"
                ):
                    await agent_events.put(("event", event))
            finally:
                await agent_events.put(("done", None))

        producer = asyncio.create_task(produce_agent_events())
        try:
            agent_done = False
            while not agent_done:
                agent_get = asyncio.create_task(agent_events.get())
                progress_get = asyncio.create_task(progress_channel.receive())
                done, pending = await asyncio.wait(
                    {agent_get, progress_get},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                ordered_done = [
                    task for task in (progress_get, agent_get) if task in done
                ]
                for task in ordered_done:
                    if task is agent_get:
                        kind, value = task.result()
                    else:
                        kind, value = "progress", task.result()
                    if kind == "done":
                        agent_done = True
                        continue
                    normalized_events = (
                        [self._progress_event(session_id, value)]
                        if isinstance(value, ProgressEvent)
                        else self._stream_events(
                            session_id,
                            value,
                            pending_tool_steps,
                        )
                    )
                    for normalized in normalized_events:
                        normalized = self._public_progress_ids(
                            normalized,
                            public_step_ids,
                        )
                        for lifecycle_event in self._thinking_lifecycle_events(
                            normalized,
                            lifecycle_statuses,
                            active_thinking_steps,
                        ):
                            if self._should_emit_stream_event(
                                lifecycle_event, seen_thinking_steps
                            ):
                                yield lifecycle_event

            try:
                await producer
            except Exception:
                for lifecycle_event in self._finalize_thinking_steps(
                    active_thinking_steps,
                    lifecycle_statuses,
                    status="failed",
                ):
                    if self._should_emit_stream_event(
                        lifecycle_event, seen_thinking_steps
                    ):
                        yield lifecycle_event
                raise
            while True:
                progress_event = progress_channel.receive_nowait()
                if progress_event is None:
                    break
                normalized = self._progress_event(session_id, progress_event)
                normalized = self._public_progress_ids(
                    normalized,
                    public_step_ids,
                )
                for lifecycle_event in self._thinking_lifecycle_events(
                    normalized,
                    lifecycle_statuses,
                    active_thinking_steps,
                ):
                    if self._should_emit_stream_event(
                        lifecycle_event, seen_thinking_steps
                    ):
                        yield lifecycle_event
            for lifecycle_event in self._finalize_thinking_steps(
                active_thinking_steps,
                lifecycle_statuses,
            ):
                if self._should_emit_stream_event(
                    lifecycle_event, seen_thinking_steps
                ):
                    yield lifecycle_event
        finally:
            if not producer.done():
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            reset_progress_channel(progress_token)
            reset_runtime_context(token)

    def _progress_event(self, session_id: str, event: ProgressEvent) -> dict[str, Any]:
        return {
            "type": ServerEventType.THINKING_STEP.value,
            "session_id": session_id,
            "content": event.summary,
            "data": {
                "step_id": event.step_id,
                "step_name": event.title,
                "status": event.status,
                "summary": event.summary,
                "summary_data": {
                    **event.data,
                    "source": event.source,
                    **({"businessId": event.business_id} if event.business_id else {}),
                },
                "phase": "middle",
            },
        }

    def _public_progress_ids(
        self,
        event: dict[str, Any],
        public_ids: dict[str, str],
    ) -> dict[str, Any]:
        if event.get("type") != ServerEventType.THINKING_STEP.value:
            return event
        data = event.get("data")
        if not isinstance(data, dict):
            return event

        normalized = dict(data)
        normalized["step_id"] = self._public_step_id(data.get("step_id"), public_ids)
        steps = data.get("steps")
        if isinstance(steps, list):
            normalized["steps"] = [
                {
                    **step,
                    "id": self._public_step_id(step.get("id"), public_ids),
                }
                if isinstance(step, dict)
                else step
                for step in steps
            ]
        for key in ("currentStep", "failedStep", "nextStep"):
            if data.get(key) is not None:
                normalized[key] = self._public_step_id(data.get(key), public_ids)
        completed_steps = data.get("completedSteps")
        if isinstance(completed_steps, list):
            normalized["completedSteps"] = [
                self._public_step_id(step_id, public_ids)
                for step_id in completed_steps
            ]
        return {**event, "data": normalized}

    def _public_step_id(
        self,
        internal_id: Any,
        public_ids: dict[str, str],
    ) -> str:
        key = str(internal_id or "").strip() or "anonymous-step"
        current = public_ids.get(key)
        if current is not None:
            return current
        try:
            public_id = str(UUID(key))
        except ValueError:
            public_id = str(uuid4())
        public_ids[key] = public_id
        return public_id

    def _stream_events(
        self,
        session_id: str,
        event: Any,
        pending_tool_steps: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_events = self._tool_lifecycle_events_from_event(
            session_id,
            event,
            pending_tool_steps,
        )
        progress = self._task_progress_from_event(event)
        progress_events = (
            self._task_progress_events(session_id, progress)
            if progress is not None
            else []
        )
        normalized = self._normalize_event(session_id, event)
        if (
            tool_events
            or progress is not None
            or self._event_has_display_tool_calls(event)
        ) and normalized.get("type") == ServerEventType.THINKING_STEP.value:
            normalized = {
                "type": ServerEventType.DST_STATE.value,
                "session_id": session_id,
                "data": self._jsonable(event),
            }
        passthrough = [] if normalized.get("type") == ServerEventType.DST_STATE.value else [normalized]
        return [*tool_events, *progress_events, *passthrough]

    def _event_has_display_tool_calls(self, event: Any) -> bool:
        for messages in self._message_sequences(event):
            for message in messages:
                if not isinstance(message, AIMessage):
                    continue
                if any(
                    isinstance(call, dict)
                    and not self._is_hidden_thinking_tool(str(call.get("name") or ""))
                    for call in (getattr(message, "tool_calls", None) or [])
                ):
                    return True
        return False

    def _tool_lifecycle_events_from_event(
        self,
        session_id: str,
        event: Any,
        pending_steps: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for messages in self._message_sequences(event):
            for message in messages:
                if isinstance(message, AIMessage):
                    for call in getattr(message, "tool_calls", None) or []:
                        if not isinstance(call, dict):
                            continue
                        tool_name = str(call.get("name") or "")
                        call_id = str(call.get("id") or "").strip()
                        if not call_id or self._is_hidden_thinking_tool(tool_name):
                            continue
                        description = self._plugin_context.tools.step(tool_name)
                        step = {
                            "type": ServerEventType.THINKING_STEP.value,
                            "session_id": session_id,
                            "content": description.summary,
                            "data": {
                                "step_id": f"framework.tool.{call_id}",
                                "step_name": description.title,
                                "status": "running",
                                "summary": description.summary,
                                "summary_data": {
                                    "source": "tool_call",
                                    "stepCount": 1,
                                },
                                "phase": "middle",
                            },
                        }
                        if call_id not in pending_steps:
                            pending_steps[call_id] = step
                            events.append(step)
                elif isinstance(message, ToolMessage):
                    call_id = str(getattr(message, "tool_call_id", "") or "").strip()
                    step = pending_steps.pop(call_id, None)
                    if step is None:
                        continue
                    data = step.get("data")
                    data = data if isinstance(data, dict) else {}
                    events.append({
                        **step,
                        "data": {
                            **data,
                            "status": self._tool_message_status(message),
                        },
                    })
        return events

    def _tool_message_status(self, message: ToolMessage) -> str:
        if getattr(message, "status", None) == "error":
            return "failed"
        try:
            payload = json.loads(self._message_content_to_text(message.content))
        except json.JSONDecodeError:
            return "completed"
        if isinstance(payload, dict) and (
            payload.get("ok") is False
            or payload.get("status") in {"failed", "error"}
        ):
            return "failed"
        return "completed"

    def _thinking_lifecycle_events(
        self,
        event: dict[str, Any],
        statuses: set[tuple[str, str]],
        active_steps: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if event.get("type") != ServerEventType.THINKING_STEP.value:
            if event.get("type") in {
                ServerEventType.MESSAGE.value,
                "human_action_required",
                ServerEventType.ERROR.value,
            }:
                return [
                    *self._finalize_thinking_steps(active_steps, statuses),
                    event,
                ]
            return [event]

        data = event.get("data")
        data = data if isinstance(data, dict) else {}
        step_id = str(data.get("step_id") or "").strip()
        status = str(data.get("status") or "running").strip().lower()
        if status == "success":
            status = "completed"
            data = {**data, "status": status}
            event = {**event, "data": data}
        if status in {"pending", "skipped"}:
            return []
        if not step_id or status not in {"running", "completed", "failed"}:
            return [event]

        events: list[dict[str, Any]] = []
        sequential_source = self._sequential_thinking_source(event)
        if status == "running" and sequential_source is not None:
            sequential_step_ids = {
                active_id
                for active_id, active_event in active_steps.items()
                if active_id != step_id
                and self._sequential_thinking_source(active_event) == sequential_source
            }
            events.extend(self._finalize_thinking_steps(
                active_steps,
                statuses,
                step_ids=sequential_step_ids,
            ))
        if status in {"completed", "failed"} and (step_id, "running") not in statuses:
            running = {
                **event,
                "data": {**data, "status": "running"},
            }
            statuses.add((step_id, "running"))
            active_steps[step_id] = running
            events.append(running)

        key = (step_id, status)
        if key in statuses:
            return events
        statuses.add(key)
        events.append(event)
        if status == "running":
            active_steps[step_id] = event
        else:
            active_steps.pop(step_id, None)
        return events

    def _finalize_thinking_steps(
        self,
        active_steps: dict[str, dict[str, Any]],
        statuses: set[tuple[str, str]],
        status: str = "completed",
        step_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for step_id, event in list(active_steps.items()):
            if step_ids is not None and step_id not in step_ids:
                continue
            active_steps.pop(step_id, None)
            key = (step_id, status)
            if key in statuses:
                continue
            statuses.add(key)
            data = event.get("data")
            data = data if isinstance(data, dict) else {}
            events.append({**event, "data": {**data, "status": status}})
        return events

    def _sequential_thinking_source(self, event: dict[str, Any]) -> str | None:
        data = event.get("data")
        data = data if isinstance(data, dict) else {}
        summary_data = data.get("summary_data")
        summary_data = summary_data if isinstance(summary_data, dict) else {}
        source = summary_data.get("source")
        return str(source) if source in {"task_progress", "tool_call"} else None

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
                plugin_context=self._plugin_context,
            )
        return RequestRuntimeContext(session_id=session_id, plugin_context=self._plugin_context)

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

        frontend_callback_completion = self._frontend_callback_completion_from_event(event)
        if frontend_callback_completion is not None:
            return {
                "type": ServerEventType.MESSAGE.value,
                "session_id": session_id,
                "content": frontend_callback_completion.get("message") or "操作已完成。",
                "data": frontend_callback_completion,
            }

        frontend_callback_requirement = self._frontend_callback_requirement_from_event(event)
        if frontend_callback_requirement is not None:
            return {
                "type": ServerEventType.MESSAGE.value,
                "session_id": session_id,
                "content": frontend_callback_requirement.get("message") or "请补充前端执行结果。",
                "data": frontend_callback_requirement,
            }

        if isinstance(event, dict) and "__interrupt__" in event:
            interrupts = self._jsonable(event["__interrupt__"])
            projected = self._plugin_context.projections.project_human_interrupt(
                interrupts if isinstance(interrupts, list) else [interrupts]
            )
            payload = {
                "type": "human_action_required",
                "session_id": session_id,
                "data": {"interrupts": interrupts},
            }
            payload.update(projected)
            return payload

        confirmation_interrupt = self._confirmation_interrupt_from_event(event)
        if confirmation_interrupt is not None:
            projected = self._plugin_context.projections.project_human_interrupt(
                [confirmation_interrupt]
            )
            payload = {
                "type": "human_action_required",
                "session_id": session_id,
                "content": confirmation_interrupt.get("question"),
                "data": {"interrupts": [confirmation_interrupt]},
            }
            payload.update(projected)
            return payload

        task_progress = self._task_progress_from_event(event)
        if task_progress is not None:
            progress_event = self._task_progress_event(session_id, task_progress)
            progress_data = progress_event.get("data")
            progress_data = progress_data if isinstance(progress_data, dict) else {}
            if progress_data.get("status") in {"running", "completed", "failed"}:
                return progress_event

        tool_step = self._tool_call_step_from_event(session_id, event)
        if tool_step is not None:
            return tool_step

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

    def _tool_call_step_from_event(self, session_id: str, event: Any) -> dict[str, Any] | None:
        for messages in self._message_sequences(event):
            if not messages:
                continue
            latest = messages[-1]
            if not isinstance(latest, AIMessage):
                continue
            tool_calls = getattr(latest, "tool_calls", None) or []
            if not tool_calls:
                continue
            tool_names = [
                str(call.get("name") or call.get("id") or "tool")
                for call in tool_calls
                if isinstance(call, dict)
                and not self._is_hidden_thinking_tool(
                    str(call.get("name") or call.get("id") or "tool")
                )
            ]
            if not tool_names:
                return None
            if any(self._is_human_input_tool(name) for name in tool_names):
                return None
            descriptions = [
                self._plugin_context.tools.step(name) for name in tool_names
            ]
            first_description = descriptions[0]
            return {
                "type": ServerEventType.THINKING_STEP.value,
                "session_id": session_id,
                "content": first_description.summary,
                "data": {
                    "step_id": f"framework.thinking.{self._stable_step_token(tool_names)}",
                    "step_name": first_description.title,
                    "status": "running",
                    "summary": "；".join(description.summary for description in descriptions),
                    "summary_data": {
                        "source": "tool_call",
                        "stepCount": len(descriptions),
                    },
                    "lifecycle": False,
                    "phase": "middle",
                },
            }
        return None

    def _should_emit_stream_event(
        self,
        event: dict[str, Any],
        seen_thinking_steps: set[tuple[str | None, str | None, str | None, str | None]],
    ) -> bool:
        if event.get("type") != ServerEventType.THINKING_STEP.value:
            return True
        data = event.get("data")
        data = data if isinstance(data, dict) else {}
        status = self._stringify(data.get("status"))
        step_id = self._stringify(data.get("step_id"))
        key = (
            status,
            step_id,
            None,
            None,
        ) if step_id else (
            status,
            self._stringify(event.get("content") or data.get("summary") or data.get("step_name")),
            self._stringify(data.get("phase")),
            None,
        )
        if key in seen_thinking_steps:
            return False
        seen_thinking_steps.add(key)
        return True

    def _stable_step_token(self, tool_names: list[str]) -> str:
        raw = "|".join(tool_names) or "tool"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]

    def _is_human_input_tool(self, tool_name: str) -> bool:
        normalized = tool_name.replace("-", "_").lower()
        return normalized in {"request_human_input", "human_input"} or normalized.endswith(".request_human_input")

    def _is_hidden_thinking_tool(self, tool_name: str) -> bool:
        normalized = tool_name.replace("-", "_").lower()
        return self._is_human_input_tool(normalized) or normalized in {
            "update_task_progress",
            "update_dialogue_state",
            "write_todos",
        }

    def _frontend_callback_completion_from_event(self, event: Any) -> dict[str, Any] | None:
        for candidate in self._candidate_dicts(event):
            if candidate.get("status") not in {"success", "updated"}:
                continue
            data = candidate.get("data")
            if not isinstance(data, dict):
                continue
            pending = data.get("pendingAction")
            if not isinstance(pending, dict) or pending.get("executionMode") != "frontend_callback":
                continue
            return {
                "status": candidate.get("status"),
                "action_id": candidate.get("action_id"),
                "message": candidate.get("message"),
                "data": self._jsonable(data),
            }
        return None

    def _frontend_callback_requirement_from_event(self, event: Any) -> dict[str, Any] | None:
        for candidate in self._candidate_dicts(event):
            if candidate.get("status") != "failed" or candidate.get("error_code") != "ACTION_RESULT_REQUIRED":
                continue
            data = candidate.get("data")
            if not isinstance(data, dict):
                continue
            pending = data.get("pendingAction")
            if not isinstance(pending, dict) or pending.get("executionMode") != "frontend_callback":
                continue
            return {
                "status": candidate.get("status"),
                "action_id": candidate.get("action_id"),
                "message": candidate.get("message"),
                "error_code": candidate.get("error_code"),
                "data": self._jsonable(data),
            }
        return None

    def _task_progress_event(self, session_id: str, progress: dict[str, Any]) -> dict[str, Any]:
        steps = progress.get("steps") if isinstance(progress.get("steps"), list) else []
        current_step = progress.get("currentStep") or self._current_progress_step_id(steps)
        current = self._progress_step_by_id(steps, current_step) or (steps[-1] if steps else {})
        status = current.get("status") or self._progress_status(progress)
        return {
            "type": ServerEventType.THINKING_STEP.value,
            "session_id": session_id,
            "content": current.get("summary") or progress.get("summary") or current.get("title"),
            "data": {
                "step_id": current.get("id") or current_step,
                "step_name": current.get("title") or current_step,
                "status": status,
                "summary": current.get("summary") or progress.get("summary") or current.get("title"),
                "summary_data": {
                    **(current.get("data") or {}),
                    "source": "task_progress",
                },
                "steps": steps,
                "currentStep": current_step,
                "completedSteps": progress.get("completedSteps") or [
                    step.get("id") for step in steps if step.get("status") == "completed"
                ],
                "failedStep": progress.get("failedStep"),
                "nextStep": progress.get("nextStep"),
            },
        }

    def _task_progress_events(
        self,
        session_id: str,
        progress: dict[str, Any],
    ) -> list[dict[str, Any]]:
        steps = progress.get("steps")
        if not isinstance(steps, list):
            return []
        events = []
        for step in steps:
            if not isinstance(step, dict) or step.get("status") not in {
                "running",
                "completed",
                "failed",
            }:
                continue
            events.append(self._task_progress_event(
                session_id,
                {**progress, "currentStep": step.get("id")},
            ))
        return events

    def _task_progress_from_event(self, event: Any) -> dict[str, Any] | None:
        payload = self._first_dict_by_key(event, "task_progress")
        if payload is None:
            payload = self._first_dict_by_key(event, "taskProgress")
        if payload is None:
            todos = self._first_list_by_key(event, "todos")
            if todos is not None:
                payload = self._progress_from_todos(todos)
        if payload is None:
            return None
        return self._normalize_task_progress(payload)

    def _normalize_task_progress(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_steps = payload.get("steps")
        if not isinstance(raw_steps, list):
            raw_steps = []
        steps = [
            self._normalize_progress_step(index, step)
            for index, step in enumerate(raw_steps)
            if isinstance(step, dict)
        ]
        current_step = payload.get("currentStep") or payload.get("current_step") or self._current_progress_step_id(steps)
        completed_steps = payload.get("completedSteps") or [
            step.get("id") for step in steps if step.get("status") == "completed"
        ]
        return {
            "steps": steps,
            "currentStep": str(current_step) if current_step else None,
            "completedSteps": [str(step_id) for step_id in completed_steps if step_id],
            "failedStep": payload.get("failedStep") or payload.get("failed_step"),
            "nextStep": payload.get("nextStep") or payload.get("next_step"),
            "summary": payload.get("summary"),
        }

    def _normalize_progress_step(self, index: int, step: dict[str, Any]) -> dict[str, Any]:
        step_id = step.get("id") or step.get("step_id") or f"step-{index + 1}"
        title = step.get("title") or step.get("name") or step.get("content") or str(step_id)
        status = str(step.get("status") or "pending").strip().lower()
        if status in {"in_progress", "active"}:
            status = "running"
        if status in {"todo", "not_started"}:
            status = "pending"
        if status not in {"pending", "running", "completed", "failed", "skipped"}:
            status = "pending"
        normalized: dict[str, Any] = {
            "id": str(step_id),
            "title": str(title).strip()[:80],
            "status": status,
        }
        summary = step.get("summary")
        if isinstance(summary, str) and summary.strip():
            normalized["summary"] = summary.strip()[:200]
        data = step.get("data")
        if isinstance(data, dict):
            normalized["data"] = self._jsonable(data)
        return normalized

    def _progress_from_todos(self, todos: list[Any]) -> dict[str, Any]:
        steps = []
        for index, todo in enumerate(todos):
            if isinstance(todo, dict):
                title = todo.get("title") or todo.get("content") or f"步骤 {index + 1}"
                steps.append({
                    "id": todo.get("id") or (
                        f"framework.todo.{hashlib.sha1(str(title).encode('utf-8')).hexdigest()[:12]}"
                    ),
                    "title": title,
                    "status": todo.get("status") or "pending",
                    "summary": todo.get("summary"),
                })
        return {"steps": steps}

    def _current_progress_step_id(self, steps: list[Any]) -> str | None:
        for status in ("running", "pending", "failed", "completed"):
            for step in steps:
                if isinstance(step, dict) and step.get("status") == status and step.get("id"):
                    return str(step["id"])
        return None

    def _progress_step_by_id(self, steps: list[Any], step_id: Any) -> dict[str, Any] | None:
        if step_id is None:
            return None
        for step in steps:
            if isinstance(step, dict) and step.get("id") == step_id:
                return step
        return None

    def _progress_status(self, progress: dict[str, Any]) -> str:
        if progress.get("failedStep"):
            return "failed"
        steps = progress.get("steps")
        if isinstance(steps, list) and steps and all(
            isinstance(step, dict) and step.get("status") == "completed" for step in steps
        ):
            return "completed"
        return "running"

    def _first_dict_by_key(self, value: Any, key: str) -> dict[str, Any] | None:
        if isinstance(value, dict):
            candidate = value.get(key)
            if isinstance(candidate, dict):
                return candidate
            for item in value.values():
                result = self._first_dict_by_key(item, key)
                if result is not None:
                    return result
        elif isinstance(value, list):
            for item in value:
                result = self._first_dict_by_key(item, key)
                if result is not None:
                    return result
        elif isinstance(value, ToolMessage):
            try:
                payload = json.loads(str(value.content))
            except json.JSONDecodeError:
                return None
            return self._first_dict_by_key(payload, key)
        return None

    def _first_list_by_key(self, value: Any, key: str) -> list[Any] | None:
        if isinstance(value, dict):
            candidate = value.get(key)
            if isinstance(candidate, list):
                return candidate
            for item in value.values():
                result = self._first_list_by_key(item, key)
                if result is not None:
                    return result
        elif isinstance(value, list):
            for item in value:
                result = self._first_list_by_key(item, key)
                if result is not None:
                    return result
        elif isinstance(value, ToolMessage):
            try:
                payload = json.loads(str(value.content))
            except json.JSONDecodeError:
                return None
            return self._first_list_by_key(payload, key)
        return None

    def _extract_latest_ai_text(self, event: Any) -> str | None:
        if not isinstance(event, dict):
            return None

        for messages in self._message_sequences(event):
            if not messages:
                continue
            latest = messages[-1]
            if isinstance(latest, AIMessage):
                if getattr(latest, "tool_calls", None):
                    continue
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
