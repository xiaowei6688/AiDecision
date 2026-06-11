"""
这是个演示角色
"""

from deepagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from app.tools.tools import DST_TOOLS


def build_role_subagents(model: BaseChatModel) -> list[SubAgent]:
    """构建主编排器使用的企业角色代理."""

    return [
        {
            "name": "requirements_analyst",
            "description": "明确用户目标、限制、缺失信息和成功标准.",
            "system_prompt": (
                "你是需求分析 Agent。你的职责是把用户模糊的表达转成清晰需求："
                "识别目标、约束、角色、输入输出、验收标准和缺失信息。"
                "每次分析后调用 update_dialogue_state 更新 intent、slots、summary。"
                "如果关键决策缺失，调用 request_human_input 请求人工确认。"
            ),
            "tools": DST_TOOLS,
            "model": model,
        },
        {
            "name": "decision_strategist",
            "description": "比较可行方案并推荐最简单的稳健决策路径.",
            "system_prompt": (
                "你是决策分析 Agent。你的职责是比较方案、权衡成本收益和风险，"
                "优先给出简单、可执行、可验证的建议。"
                "需要保留对话状态时调用 update_dialogue_state。"
            ),
            "tools": DST_TOOLS,
            "model": model,
        },
        {
            "name": "risk_reviewer",
            "description": "审查安全性、可靠性、数据一致性和操作风险.",
            "system_prompt": (
                "你是风险审查 Agent。你的职责是审查方案中的安全、隐私、"
                "可靠性、成本、合规和可运维风险。遇到高风险动作必须调用 "
                "request_human_input 等待人工确认。"
            ),
            "tools": DST_TOOLS,
            "model": model,
        },
        {
            "name": "execution_planner",
            "description": "将已接受的决策转化为有序的实施步骤和验收检查.",
            "system_prompt": (
                "你是执行规划 Agent。你的职责是把确认后的方案拆成步骤、接口、"
                "数据结构和验收检查。输出要简洁、明确、可执行。"
            ),
            "tools": DST_TOOLS,
            "model": model,
        },
    ]
