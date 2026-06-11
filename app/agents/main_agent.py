from typing import Any

from deepagents import create_deep_agent
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.llm import build_chat_model
from app.agents.middleware import SummaryInjectionMiddleware
from app.agents.state import DecisionDSTState
from app.agents.roles.subagents import build_role_subagents
from app.tools.base_tool import DST_TOOLS
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

委派给 SubAgent 时（调用 task 工具），description 必须自包含：
- SubAgent 是无状态的，每次都是全新启动，看不到本次对话历史，也不记得之前任何一次
  SubAgent 跑过什么。它只能看到你写的 description，加上系统注入的已压缩 summary。
- 因此 description 必须包含 SubAgent 完成任务所需的全部背景：用户的原始目标、已确认的
  关键事实（slots）、之前相关结论、以及这一次具体要它做什么、期望输出什么格式。
- 特别是人工交互（HITL）被取消又恢复、或用户中途补充新信息后：不要只把“新增内容”塞进
  description。必须把新信息与之前的上下文重新合成为一段完整、自洽的任务说明，否则
  SubAgent 会因为信息缺失而执行出错。
- 绝不要假设 SubAgent “应该记得”或“会自己去查”——需要它知道的，就明确写进 description。

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
