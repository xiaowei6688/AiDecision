from typing import Any
import asyncio
import json

from langchain_core.messages import AIMessage, ToolMessage

from app.integrations.inspection.ui import inspection_human_interrupt_projection
from app.integrations.context import PluginContext
from app.services.session_service import SessionService
from app.core.progress import get_progress_channel
from app.core.runtime_context import get_runtime_context


class Overwrite:
    def __init__(self, value: Any) -> None:
        self.value = value


class StreamingAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        yield {"messages": [AIMessage(content="done")]}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {}})()


class DuplicateToolCallStreamingAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        event = {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"name": "dedupe_semantic_query", "id": "call-1", "args": {}}],
                )
            ]
        }
        yield event
        yield event
        yield {"messages": [AIMessage(content="done")]}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {}})()


class LiveProgressStreamingAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        channel = get_progress_channel()
        assert channel is not None
        session_id = get_runtime_context().session_id
        channel.publish(
            session_id=session_id,
            source="tool_broker",
            business_id="inventory",
            step_id=f"step-{session_id}",
            title="核对库存事实",
            summary=f"正在核对 {session_id} 的库存",
            status="running",
        )
        await asyncio.sleep(0.02)
        channel.publish(
            session_id=session_id,
            source="tool_broker",
            business_id="inventory",
            step_id=f"step-{session_id}",
            title="核对库存事实",
            summary=f"正在核对 {session_id} 的库存",
            status="completed",
        )
        yield {
            "task_progress": {
                "steps": [{
                    "id": f"step-{session_id}",
                    "title": "核对库存事实",
                    "summary": f"正在核对 {session_id} 的库存",
                    "status": "completed",
                }],
                "currentStep": f"step-{session_id}",
            }
        }
        yield {"messages": [AIMessage(content=f"done-{session_id}")]}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {}})()


def test_extract_latest_ai_text_handles_langgraph_overwrite_messages() -> None:
    service = SessionService(agent=None)
    event = {"agent": {"messages": Overwrite([AIMessage(content="hello")])}}

    assert service._extract_latest_ai_text(event) == "hello"


async def _collect_stream(service: SessionService) -> list[dict[str, Any]]:
    return [
        event
        async for event in service.stream_message("session-1", "hello")
    ]


def test_stream_message_does_not_emit_lifecycle_start_or_end() -> None:
    service = SessionService(agent=StreamingAgent())

    events = __import__("asyncio").run(_collect_stream(service))

    assert len(events) == 1
    assert events[0]["type"] == "message"
    assert events[0]["content"] == "done"


def test_stream_message_emits_progress_before_agent_finishes() -> None:
    service = SessionService(agent=LiveProgressStreamingAgent())

    events = asyncio.run(_collect_stream(service))

    assert [event["type"] for event in events] == [
        "thinking_step",
        "thinking_step",
        "message",
    ]
    assert [event["data"]["status"] for event in events[:2]] == [
        "running",
        "completed",
    ]
    assert events[0]["data"]["step_id"] == events[1]["data"]["step_id"]
    assert events[2]["content"] == "done-session-1"


def test_stream_progress_channels_are_isolated_between_sessions() -> None:
    service = SessionService(agent=LiveProgressStreamingAgent())

    async def collect_both() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return await asyncio.gather(
            _collect_stream_for_session(service, "session-a"),
            _collect_stream_for_session(service, "session-b"),
        )

    first, second = asyncio.run(collect_both())

    assert all("session-b" not in str(event) for event in first)
    assert all("session-a" not in str(event) for event in second)


async def _collect_stream_for_session(
    service: SessionService, session_id: str
) -> list[dict[str, Any]]:
    return [event async for event in service.stream_message(session_id, "hello")]


def test_extract_latest_ai_text_ignores_non_sequence_overwrite_messages() -> None:
    service = SessionService(agent=None)
    event = {"agent": {"messages": Overwrite({"not": "a message list"})}}

    assert service._extract_latest_ai_text(event) is None


def test_normalize_event_returns_message_for_top_level_messages() -> None:
    service = SessionService(agent=None)
    event = {"messages": [AIMessage(content="resume answer")]}

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "message"
    assert normalized["content"] == "resume answer"


def test_normalize_event_converts_confirmation_tool_result_to_human_action_required() -> None:
    context = PluginContext()
    context.projections.register_human_interrupt(inspection_human_interrupt_projection)
    service = SessionService(agent=None, plugin_context=context)
    tool_result = {
        "status": "requires_confirmation",
        "action_id": "inspection.create_work_order",
        "message": "请确认是否创建以下巡检工单",
        "data": {
            "confirmation_token": "token-1",
            "params": {"planGuid": "plan-1"},
        },
        "businessId": "inspection",
        "actionCode": "createTempOrder",
        "routePath": "/workOrder/review",
        "executeApi": "/order/createTempOrder",
        "executeMethod": "POST",
        "executePayload": {"planGuid": "plan-1"},
    }
    event = {
        "tools": {
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result, ensure_ascii=False),
                    tool_call_id="tool-call-1",
                )
            ]
        }
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "human_action_required"
    assert normalized["session_id"] == "session-1"
    assert normalized["content"] == "请确认是否创建以下巡检工单"
    assert normalized["data"]["businessId"] == "inspection"
    assert normalized["data"]["actionCode"] == "createTempOrder"
    assert normalized["data"]["executeApi"] == "/order/createTempOrder"
    assert normalized["data"]["executePayload"] == {"planGuid": "plan-1"}
    assert normalized["data"]["confirmation_token"] == "token-1"


def test_normalize_event_converts_task_progress_tool_result_to_thinking_step() -> None:
    service = SessionService(agent=None)
    tool_result = {
        "task_progress": {
            "steps": [
                {"id": "query", "title": "查询线路杆塔数据", "status": "completed"},
                {"id": "assemble", "title": "组装确认信息", "status": "running", "summary": "正在生成确认数据"},
            ],
            "currentStep": "assemble",
            "completedSteps": ["query"],
            "nextStep": None,
        }
    }
    event = {
        "tools": {
            "messages": [
                ToolMessage(
                    content=json.dumps(tool_result, ensure_ascii=False),
                    tool_call_id="tool-call-1",
                )
            ]
        }
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "thinking_step"
    assert normalized["session_id"] == "session-1"
    assert normalized["content"] == "正在生成确认数据"
    assert normalized["data"]["step_id"] == "assemble"
    assert normalized["data"]["step_name"] == "组装确认信息"
    assert normalized["data"]["status"] == "running"
    assert normalized["data"]["completedSteps"] == ["query"]
    assert normalized["data"]["steps"][0]["title"] == "查询线路杆塔数据"


def test_normalize_event_prefers_frontend_callback_completion_over_confirmation() -> None:
    service = SessionService(agent=None)
    event = {
        "tools": {
            "messages": [
                ToolMessage(
                    content=json.dumps(
                        {
                            "status": "success",
                            "action_id": "inspection.create_plan",
                            "message": "巡检计划已创建成功",
                            "data": {
                                "pendingAction": {
                                    "executionMode": "frontend_callback",
                                    "actionCode": "createPlan",
                                },
                                "frontendResult": {"success": True, "planGuid": "plan-1"},
                            },
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="tool-call-1",
                )
            ]
        }
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "message"
    assert normalized["content"] == "巡检计划已创建成功"
    assert normalized["data"]["data"]["frontendResult"]["planGuid"] == "plan-1"


def test_normalize_event_converts_tool_calls_to_intermediate_thinking_step() -> None:
    context = PluginContext()
    context.tools.register_step(
        "semantic_query",
        "核对业务数据",
        "正在基于当前问题核对业务数据来源",
    )
    service = SessionService(agent=None, plugin_context=context)
    event = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "semantic_query", "id": "call-1", "args": {}}],
            )
        ]
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "thinking_step"
    assert normalized["data"]["phase"] == "middle"
    assert normalized["data"]["step_id"].startswith("framework.thinking.")
    assert normalized["data"]["step_name"] == "核对业务数据"
    assert normalized["content"] == "正在基于当前问题核对业务数据来源"
    assert normalized["data"]["summary_data"] == {"source": "tool_call", "stepCount": 1}


def test_normalize_event_does_not_expose_unregistered_tool_name() -> None:
    service = SessionService(agent=None)
    tool_name = "some_internal_tool_name"
    event = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": tool_name, "id": "call-1", "args": {}}],
            )
        ]
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "thinking_step"
    assert normalized["content"] == "正在核对与 Some internal tool name 相关的事实和条件"
    assert tool_name not in normalized["content"]


def test_normalize_event_does_not_emit_thinking_step_for_human_input_tool_call() -> None:
    service = SessionService(agent=None)
    event = {
        "messages": [
            AIMessage(
                content="",
                tool_calls=[{"name": "request_human_input", "id": "call-1", "args": {}}],
            )
        ]
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "dst_state"


def test_stream_message_deduplicates_repeated_thinking_steps() -> None:
    context = PluginContext()
    context.tools.register_step(
        "dedupe_semantic_query",
        "核对业务数据",
        "正在基于当前问题核对业务数据来源",
    )
    service = SessionService(
        agent=DuplicateToolCallStreamingAgent(), plugin_context=context
    )

    events = __import__("asyncio").run(_collect_stream(service))

    assert [event["type"] for event in events] == ["thinking_step", "message"]
    assert events[0]["content"] == "正在基于当前问题核对业务数据来源"
    assert events[1]["content"] == "done"
