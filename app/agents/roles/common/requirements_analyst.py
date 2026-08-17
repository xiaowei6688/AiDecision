from deepagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.middleware import SummaryInjectionMiddleware
from app.tools.base_tool import request_human_input, update_dialogue_state


def build_requirements_analyst(model: BaseChatModel) -> SubAgent:
    return {
        "name": "requirements_analyst",
        "description": "明确用户目标、限制、缺失信息和成功标准.",
        "system_prompt": (
            "你是需求分析 Agent。你的职责是把用户模糊的表达转成清晰需求："
            "识别目标、约束、角色、输入输出、验收标准和缺失信息。"
            "每次分析后调用 update_dialogue_state 更新 intent、slots、summary。"
            "如果只是缺少普通信息，直接用自然语言向用户追问，不要调用 request_human_input。"
            "只有需要用户审批、确认可执行动作或处理高风险决定时，才调用 request_human_input。"
        ),
        "tools": [update_dialogue_state, request_human_input],
        "model": model,
        "middleware": [SummaryInjectionMiddleware()],
    }
