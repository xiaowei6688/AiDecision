from deepagents import SubAgent
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.roles.common.requirements_analyst import (
    build_requirements_analyst,
)


def build_role_subagents(model: BaseChatModel) -> list[SubAgent]:
    """Build subagents used by the main orchestrator.

    Domain experts are loaded dynamically through consult_domain_expert instead
    of being registered as always-on deepagents subagents.
    """

    return [
        build_requirements_analyst(model),
    ]
