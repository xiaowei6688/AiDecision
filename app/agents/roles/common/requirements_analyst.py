from deepagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.middleware import SummaryInjectionMiddleware
from app.tools.base_tool import HUMAN_INPUT_TOOLS


def build_requirements_analyst(model: BaseChatModel) -> SubAgent:
    return {
        "name": "requirements_analyst",
        "description": "明确用户目标、限制、缺失信息和成功标准.",
        "system_prompt": (
            "你是需求分析 Agent。你的职责是把用户模糊的表达转成清晰需求："
            "识别目标、约束、角色、输入输出、验收标准和缺失信息。"
            "每次分析后调用 update_dialogue_state 更新 intent、slots、summary。"
            "如果关键决策缺失，调用 request_human_input 请求人工确认。"
        ),
        "tools": HUMAN_INPUT_TOOLS,
        "model": model,
        "middleware": [SummaryInjectionMiddleware()],
    }
