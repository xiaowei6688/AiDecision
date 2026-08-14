from typing import Any
import json

from langchain_core.messages import AIMessage, ToolMessage

from app.integrations.inspection.ui import inspection_human_interrupt_projection
from app.integrations.projections import register_human_interrupt_projection
from app.services.session_service import SessionService


class Overwrite:
    def __init__(self, value: Any) -> None:
        self.value = value


def test_extract_latest_ai_text_handles_langgraph_overwrite_messages() -> None:
    service = SessionService(agent=None)
    event = {"agent": {"messages": Overwrite([AIMessage(content="hello")])}}

    assert service._extract_latest_ai_text(event) == "hello"


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
    service = SessionService(agent=None)
    register_human_interrupt_projection(inspection_human_interrupt_projection)
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
