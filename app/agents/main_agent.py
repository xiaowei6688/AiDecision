from typing import Any

from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.llm import build_chat_model
from app.agents.middleware import SummaryInjectionMiddleware
from app.agents.state import DecisionDSTState
from app.agents.roles.subagents import build_role_subagents
from app.tools.tools import DST_TOOLS
from app.core.config import Settings

"""
这是一个演示的决策Agent
"""

MAIN_AGENT_PROMPT = """你是企业级 AI 决策系统的主 Agent，也是对话状态追踪器的编排者。

你必须遵守以下工作方式：
1. 先理解用户意图，再决定是否委派给角色 SubAgent。
2. 对话中持续维护 DST：intent、slots、dialogue_stage、summary、last_active_agent。
3. 用户表达不清时，优先让 requirements_analyst 澄清需求。
4. 需要比较方案时，委派给 decision_strategist。
5. 涉及安全、隐私、成本、不可逆操作时，委派给 risk_reviewer，必要时请求人工确认。
6. 方案确认后，委派给 execution_planner 输出执行步骤。
7. 回复用户时使用清楚、简洁、容易理解的中文。

你可以调用 update_dialogue_state 写入结构化 DST，也可以调用 request_human_input
暂停流程并等待前端/人工恢复。
"""


def build_main_agent(
    settings: Settings,
    checkpointer: BaseCheckpointSaver,
) -> Any:
    """使用PostgreSQL支持的检查点创建主deepagents图."""

    chat_model = build_chat_model(settings)

    return create_deep_agent(
        model=chat_model,
        tools=DST_TOOLS,
        system_prompt=MAIN_AGENT_PROMPT,
        subagents=build_role_subagents(chat_model),
        middleware=[SummaryInjectionMiddleware()],
        state_schema=DecisionDSTState,
        checkpointer=checkpointer,
        debug=settings.environment == "development",
        name="ai_decision_main_agent",
    )
