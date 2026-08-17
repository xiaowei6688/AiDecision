from typing import Any
import asyncio
import json
from uuid import UUID

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


class RuntimeMetadataStreamingAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        continuation = get_runtime_context().metadata.get("business_continuation")
        yield {"messages": [AIMessage(content=json.dumps(continuation))]}

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


class CompletedProgressStreamingAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        yield {
            "task_progress": {
                "steps": [{
                    "id": "assemble-plan",
                    "title": "整理计划确认信息",
                    "status": "completed",
                }]
            }
        }
        yield {"messages": [AIMessage(content="done")]}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {}})()


class ProgressInterruptStreamingAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        yield {
            "todos": [{
                "content": "整理待确认的计划数据",
                "status": "in_progress",
            }]
        }
        yield {"__interrupt__": [{"question": "请确认是否创建计划"}]}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {}})()


class MultipleRunningStepsAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        yield {
            "task_progress": {
                "steps": [
                    {"id": "query", "title": "核对线路数据", "status": "running"},
                    {"id": "assemble", "title": "整理计划数据", "status": "running"},
                    {"id": "confirm", "title": "生成确认信息", "status": "running"},
                ]
            }
        }
        yield {"messages": [AIMessage(content="done")]}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {}})()


class NestedToolProgressAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        yield {
            "task_progress": {
                "steps": [{
                    "id": "query-task",
                    "title": "核对线路数据",
                    "status": "running",
                }]
            }
        }
        yield {
            "messages": [AIMessage(
                content="",
                tool_calls=[{"name": "semantic_query", "id": "call-1", "args": {}}],
            )]
        }
        yield {"messages": [AIMessage(content="done")]}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {}})()


class PendingProgressAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        yield {
            "task_progress": {
                "steps": [{
                    "id": "query-devices",
                    "title": "查询线路杆塔信息",
                    "status": "pending",
                    "summary": "正在获取指定线路和杆塔范围的设备数据",
                }]
            }
        }
        yield {"messages": [AIMessage(content="请补充杆塔范围")]}

    async def aget_state(self, config: dict[str, Any]) -> Any:
        return type("Snapshot", (), {"values": {}})()


class InternalAndBusinessToolAgent:
    async def astream(self, payload: dict[str, Any], **kwargs: Any):
        yield {
            "messages": [AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "update_task_progress",
                        "id": "progress-call",
                        "args": {},
                    },
                    {
                        "name": "inspection_query_coverage",
                        "id": "coverage-call",
                        "args": {},
                    },
                ],
            )]
        }
        yield {
            "messages": [ToolMessage(
                content=json.dumps({"ok": True, "coverage": []}),
                tool_call_id="coverage-call",
            )]
        }
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


def test_stream_message_exposes_request_metadata_to_runtime_tools() -> None:
    service = SessionService(agent=RuntimeMetadataStreamingAgent())
    continuation = {
        "businessId": "inspection",
        "operation": "create_work_orders_from_plan",
        "planId": "plan-1",
    }

    async def collect() -> list[dict[str, Any]]:
        return [
            event
            async for event in service.stream_message(
                "session-1",
                "continue",
                {"business_continuation": continuation},
            )
        ]

    events = asyncio.run(collect())

    assert json.loads(events[0]["content"]) == continuation


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


def test_completed_progress_backfills_running_with_the_same_step_id() -> None:
    service = SessionService(agent=CompletedProgressStreamingAgent())

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
    step_id = events[0]["data"]["step_id"]
    UUID(step_id)
    assert events[1]["data"]["step_id"] == step_id
    assert events[1]["data"]["currentStep"] == step_id
    assert events[1]["data"]["steps"][0]["id"] == step_id


def test_active_progress_is_completed_before_human_action_required() -> None:
    service = SessionService(agent=ProgressInterruptStreamingAgent())

    events = asyncio.run(_collect_stream(service))

    thinking = [event for event in events if event["type"] == "thinking_step"]
    human = [event for event in events if event["type"] == "human_action_required"]
    assert [event["data"]["status"] for event in thinking] == [
        "running",
        "completed",
    ]
    assert thinking[0]["data"]["step_id"] == thinking[1]["data"]["step_id"]
    assert human
    assert events.index(thinking[1]) < events.index(human[0])


def test_sequential_steps_complete_before_the_next_step_starts() -> None:
    service = SessionService(agent=MultipleRunningStepsAgent())

    events = asyncio.run(_collect_stream(service))
    thinking = [event for event in events if event["type"] == "thinking_step"]

    assert [event["data"]["status"] for event in thinking] == [
        "running",
        "completed",
        "running",
        "completed",
        "running",
        "completed",
    ]
    step_ids = [event["data"]["step_id"] for event in thinking]
    for step_id in step_ids:
        UUID(step_id)
    assert step_ids[0] == step_ids[1]
    assert step_ids[2] == step_ids[3]
    assert step_ids[4] == step_ids[5]
    assert len({step_ids[0], step_ids[2], step_ids[4]}) == 3
    assert events[-1]["type"] == "message"


def test_nested_tool_does_not_prematurely_complete_parent_task_step() -> None:
    service = SessionService(agent=NestedToolProgressAgent())

    events = asyncio.run(_collect_stream(service))
    thinking = [event for event in events if event["type"] == "thinking_step"]

    assert [event["data"]["status"] for event in thinking[:2]] == [
        "running",
        "running",
    ]
    UUID(thinking[0]["data"]["step_id"])
    assert thinking[1]["data"]["summary_data"]["source"] == "tool_call"
    assert [event["data"]["status"] for event in thinking[2:]] == [
        "completed",
        "completed",
    ]


def test_pending_progress_is_not_emitted_to_frontend() -> None:
    service = SessionService(agent=PendingProgressAgent())

    events = asyncio.run(_collect_stream(service))

    assert [event["type"] for event in events] == ["message"]
    assert events[0]["content"] == "请补充杆塔范围"


def test_internal_progress_tool_is_hidden_and_business_tool_completes_immediately() -> None:
    context = PluginContext()
    context.tools.register_step(
        "inspection_query_coverage",
        "分析巡检覆盖条件",
        "正在结合机场覆盖情况判断可用的巡检方式",
    )
    service = SessionService(
        agent=InternalAndBusinessToolAgent(),
        plugin_context=context,
    )

    events = asyncio.run(_collect_stream(service))
    thinking = [event for event in events if event["type"] == "thinking_step"]

    assert [event["data"]["status"] for event in thinking] == [
        "running",
        "completed",
    ]
    UUID(thinking[0]["data"]["step_id"])
    assert thinking[1]["data"]["step_id"] == thinking[0]["data"]["step_id"]
    assert all("Update task progress" not in str(event) for event in events)
    assert [event["type"] for event in events] == [
        "thinking_step",
        "thinking_step",
        "message",
    ]


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


def test_direct_action_failure_is_forwarded_without_internal_marker() -> None:
    service = SessionService(agent=None)
    event = {
        "messages": [ToolMessage(
            content=json.dumps({
                "status": "failed",
                "action_id": "inventory.create_record",
                "message": "业务规则校验未通过。",
                "error_code": "POLICY_REJECTED",
                "_framework": {"return_direct": True},
            }),
            tool_call_id="direct-action-1",
        )]
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "error"
    assert normalized["content"] == "业务规则校验未通过。"
    assert normalized["data"]["error_code"] == "POLICY_REJECTED"
    assert "_framework" not in normalized["data"]


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


def test_normalize_event_prefers_resume_completion_over_stale_pending_progress() -> None:
    service = SessionService(agent=None)
    event = {
        "metadata": {
            "task_progress": {
                "steps": [{
                    "id": "step-1",
                    "title": "确认线路和杆塔范围",
                    "status": "pending",
                }]
            }
        },
        "tools": {
            "messages": [ToolMessage(
                content=json.dumps({
                    "status": "success",
                    "action_id": "inspection.create_plan",
                    "message": "巡检计划已创建成功",
                    "data": {
                        "pendingAction": {
                            "executionMode": "frontend_callback",
                            "actionCode": "createPlan",
                        },
                        "frontendResult": {"success": True},
                        "final": True,
                    },
                }, ensure_ascii=False),
                tool_call_id="tool-call-1",
            )]
        },
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "message"
    assert normalized["content"] == "巡检计划已创建成功"


def test_normalize_event_does_not_expose_pending_progress() -> None:
    service = SessionService(agent=None)
    event = {
        "task_progress": {
            "steps": [{
                "id": "step-1",
                "title": "确认线路和杆塔范围",
                "status": "pending",
            }]
        }
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "dst_state"


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


def test_human_input_tool_narration_is_not_emitted_as_message() -> None:
    service = SessionService(agent=None)
    event = {
        "messages": [
            AIMessage(
                content="现在我需要请求用户确认执行计划：\n\n",
                tool_calls=[{
                    "name": "request_human_input",
                    "id": "call-1",
                    "args": {"question": "请确认是否执行"},
                }],
            )
        ]
    }

    normalized = service._normalize_event("session-1", event)

    assert normalized["type"] == "dst_state"
    assert normalized.get("content") is None


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

    assert [event["type"] for event in events] == [
        "thinking_step",
        "thinking_step",
        "message",
    ]
    assert events[0]["content"] == "正在基于当前问题核对业务数据来源"
    assert [event["data"]["status"] for event in events[:2]] == [
        "running",
        "completed",
    ]
    assert events[0]["data"]["step_id"] == events[1]["data"]["step_id"]
    assert events[2]["content"] == "done"
