from deepagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.roles.common.requirements_analyst import (
    build_requirements_analyst,
)


def build_role_subagents(model: BaseChatModel) -> list[SubAgent]:
    """Build subagents used by the main orchestrator.

    Business Agents are registered by production integrations and orchestrated
    separately; only common role SubAgents belong in this list.
    """

    return [
        build_requirements_analyst(model),
    ]
