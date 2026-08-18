from deepagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.roles.common.requirements_analyst import (
    build_requirements_analyst,
)


def build_role_subagents(model: BaseChatModel) -> list[SubAgent]:
    """构建主编排 Agent 使用的子 Agent。

    业务 Agent 由生产环境集成注册并单独编排；此列表只包含通用角色子 Agent。
    """

    return [
        build_requirements_analyst(model),
    ]
