from langchain.agents.middleware.types import ModelResponse
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.middleware import (
    SUMMARY_HEADER,
    BusinessContinuationMiddleware,
    ConfirmationProtocolMiddleware,
    DirectResultMiddleware,
    ModelProgressProtocolMiddleware,
    SummaryInjectionMiddleware,
)
from app.integrations.inspection.actions import CREATE_PLAN


def _make_request(state, system_text="基础系统提示", message="你好"):
    from langchain.agents.middleware.types import ModelRequest

    class _Model:
        pass

    return ModelRequest(
        model=_Model(),
        messages=[HumanMessage(content=message)],
        system_message=SystemMessage(content=system_text) if system_text else None,
        state=state,
    )


def test_direct_result_middleware_forwards_action_without_model_call() -> None:
    middleware = DirectResultMiddleware()
    request = _make_request({"messages": []})
    request = request.override(messages=[ToolMessage(
        content=json.dumps({
            "_framework": {
                "direct_action": {
                    "kind": "action",
                    "action_id": "inventory.create_record",
                    "params": {"name": "record-1"},
                }
            }
        }),
        tool_call_id="continue-1",
    )])

    result = middleware.wrap_model_call(
        request,
        lambda _: (_ for _ in ()).throw(AssertionError("model must not be called")),
    )

    call = result.result[0].tool_calls[0]
    assert call["name"] == "call_business_action"
    assert call["args"] == {
        "action_id": "inventory.create_record",
        "params": {"name": "record-1"},
        "return_direct": True,
    }


def test_direct_result_middleware_finishes_without_model_summary() -> None:
    middleware = DirectResultMiddleware()
    request = _make_request({"messages": []}).override(messages=[ToolMessage(
        content=json.dumps({
            "status": "success",
            "_framework": {"return_direct": True},
        }),
        tool_call_id="action-1",
    )])

    result = middleware.wrap_model_call(
        request,
        lambda _: (_ for _ in ()).throw(AssertionError("model must not be called")),
    )

    assert result.result[0].content == ""
    assert result.result[0].tool_calls == []


def test_summary_is_appended_to_system_message() -> None:
    middleware = SummaryInjectionMiddleware()
    captured: dict = {}

    def handler(request):
        captured["request"] = request
        return "ok"

    state = {"messages": [], "summary": "用户想规划 Q3 会议；已确认参会人张三李四。"}
    result = middleware.wrap_model_call(_make_request(state), handler)

    assert result == "ok"
    injected = captured["request"].system_message.text
    assert "基础系统提示" in injected
    assert SUMMARY_HEADER in injected
    assert "Q3 会议" in injected


def test_no_summary_leaves_request_unchanged() -> None:
    middleware = SummaryInjectionMiddleware()
    captured: dict = {}

    def handler(request):
        captured["request"] = request
        return "ok"

    state = {"messages": [], "summary": ""}
    request = _make_request(state)
    middleware.wrap_model_call(request, handler)

    assert captured["request"].system_message.text == "基础系统提示"
    assert SUMMARY_HEADER not in captured["request"].system_message.text


def test_summary_injected_when_no_base_system_message() -> None:
    middleware = SummaryInjectionMiddleware()
    captured: dict = {}

    def handler(request):
        captured["request"] = request
        return "ok"

    state = {"messages": [], "summary": "历史要点"}
    request = _make_request(state, system_text=None)
    middleware.wrap_model_call(request, handler)

    injected = captured["request"].system_message.text
    assert SUMMARY_HEADER in injected
    assert "历史要点" in injected


def test_async_wrap_injects_summary() -> None:
    import asyncio

    middleware = SummaryInjectionMiddleware()
    captured: dict = {}

    async def handler(request):
        captured["request"] = request
        return "ok"

    async def run():
        state = {"messages": [], "summary": "异步历史"}
        return await middleware.awrap_model_call(_make_request(state), handler)

    result = asyncio.run(run())

    assert result == "ok"
    assert "异步历史" in captured["request"].system_message.text


def test_business_continuation_forces_direct_business_agent_consultation() -> None:
    middleware = BusinessContinuationMiddleware()
    captured: dict = {}
    continuation = {
        "businessId": "inspection",
        "operation": "create_work_orders_from_plan",
        "planId": "plan-1",
    }

    def handler(request):
        captured["request"] = request
        return "ok"

    result = middleware.wrap_model_call(
        _make_request(
            {"metadata": {"business_continuation": continuation}},
            message=f"businessContinuation: {continuation}",
        ),
        handler,
    )

    assert captured == {}
    assert isinstance(result, ModelResponse)
    tool_call = result.result[0].tool_calls[0]
    assert tool_call["name"] == "continue_business_workflow"
    assert tool_call["args"] == {}


def test_business_continuation_does_not_affect_normal_user_message() -> None:
    middleware = BusinessContinuationMiddleware()
    captured: dict = {}

    def handler(request):
        captured["request"] = request
        return "ok"

    middleware.wrap_model_call(
        _make_request({
            "metadata": {
                "business_continuation": {
                    "businessId": "inspection",
                    "operation": "create_work_orders_from_plan",
                }
            }
        }),
        handler,
    )

    assert captured["request"].tool_choice is None


def test_model_progress_protocol_requires_model_declared_progress_before_tool_work() -> None:
    middleware = ModelProgressProtocolMiddleware()
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return ModelResponse(result=[AIMessage(
                content="",
                tool_calls=[{
                    "name": "semantic_query",
                    "id": "query-1",
                    "args": {"question": "查询设备"},
                }],
            )])
        return ModelResponse(result=[AIMessage(
            content="",
            tool_calls=[{
                "name": "update_task_progress",
                "id": "progress-1",
                "args": {
                    "steps": [
                        {"id": "check", "title": "核对设备范围", "status": "running"},
                        {"id": "assemble", "title": "整理巡检数据", "status": "pending"},
                    ],
                },
            }],
        )])

    result = middleware.wrap_model_call(_make_request({"messages": []}), handler)

    assert len(requests) == 2
    assert requests[1].tool_choice == "update_task_progress"
    assert "第一步 status=running" in requests[1].system_message.text
    assert result.result[0].tool_calls[0]["name"] == "update_task_progress"


def test_model_progress_protocol_does_not_repeat_existing_progress_call() -> None:
    middleware = ModelProgressProtocolMiddleware()
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return ModelResponse(result=[AIMessage(
            content="",
            tool_calls=[{
                "name": "update_task_progress",
                "id": "progress-1",
                "args": {"steps": []},
            }],
        )])

    middleware.wrap_model_call(_make_request({"messages": []}), handler)

    assert calls == 1


def test_model_progress_protocol_uses_existing_active_progress_plan() -> None:
    middleware = ModelProgressProtocolMiddleware()
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return ModelResponse(result=[AIMessage(
            content="",
            tool_calls=[{
                "name": "semantic_query",
                "id": "query-1",
                "args": {"question": "查询设备"},
            }],
        )])

    result = middleware.wrap_model_call(_make_request({
        "messages": [],
        "metadata": {
            "task_progress": {
                "steps": [
                    {"id": "check", "status": "running"},
                    {"id": "assemble", "status": "pending"},
                ]
            }
        },
    }), handler)

    assert calls == 1
    assert result.result[0].tool_calls[0]["name"] == "semantic_query"


def test_confirmation_protocol_retries_registered_action_confirmation() -> None:
    middleware = ConfirmationProtocolMiddleware([CREATE_PLAN])
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return ModelResponse(result=[AIMessage(content=(
                "我已准备好为您创建临时巡检计划，详情如下：\n\n"
                "- 计划类型：临时计划\n- 计划名称：临时计划-2026-08-23-线路巡检\n"
                "请确认是否要创建此临时巡检计划。您可以回复\"是\"或\"否\"。"
            ))])
        return ModelResponse(result=[AIMessage(
            content="",
            tool_calls=[{
                "name": "call_business_action",
                "id": "call-1",
                "args": {"action_id": "inspection.create_plan", "params": {}},
            }],
        )])

    result = middleware.wrap_model_call(_make_request({"messages": []}), handler)

    assert len(requests) == 2
    assert requests[1].tool_choice == "call_business_action"
    assert "禁止用普通 assistant 文本请求用户确认业务动作" in (
        requests[1].system_message.text
    )
    assert result.result[0].tool_calls[0]["name"] == "call_business_action"


def test_confirmation_protocol_keeps_missing_field_question_as_message() -> None:
    middleware = ConfirmationProtocolMiddleware([CREATE_PLAN])
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return ModelResponse(result=[AIMessage(content=(
            "请补充巡检日期，并确认线路名称是否为10kV十九线。"
        ))])

    result = middleware.wrap_model_call(_make_request({"messages": []}), handler)

    assert calls == 1
    assert result.result[0].content == "请补充巡检日期，并确认线路名称是否为10kV十九线。"
