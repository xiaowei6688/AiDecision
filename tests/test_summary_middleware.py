from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.middleware import SUMMARY_HEADER, SummaryInjectionMiddleware


def _make_request(state, system_text="基础系统提示"):
    from langchain.agents.middleware.types import ModelRequest

    class _Model:
        pass

    return ModelRequest(
        model=_Model(),
        messages=[HumanMessage(content="你好")],
        system_message=SystemMessage(content=system_text) if system_text else None,
        state=state,
    )


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
