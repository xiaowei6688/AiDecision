from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver

from app.agents.llm import build_chat_model
from deepagents import create_deep_agent

from app.agents.middleware import (
    BusinessContinuationMiddleware,
    ConfirmationProtocolMiddleware,
    DirectResultMiddleware,
    SummaryInjectionMiddleware,
)
from app.agents.state import DecisionDSTState
from app.agents.roles.bootstrap import build_role_subagents
from app.agents.prompts import DECISION_AGENT_PROMPT
from app.tools.dynamic_tools import build_agent_tools
from app.core.config import Settings
from app.integrations.context import PluginContext


def build_main_agent(
    settings: Settings,
    checkpointer: BaseCheckpointSaver,
    plugin_context: PluginContext | None = None,
) -> Any:
    """Build the single orchestrating DeepAgent graph."""

    chat_model = build_chat_model(settings)
    return create_deep_agent(
        model=chat_model,
        tools=build_agent_tools(chat_model, plugin_context),
        system_prompt=DECISION_AGENT_PROMPT,
        subagents=build_role_subagents(chat_model),
        middleware=[
            SummaryInjectionMiddleware(),
            BusinessContinuationMiddleware(),
            DirectResultMiddleware(),
            ConfirmationProtocolMiddleware(plugin_context.action_registry.list()),
        ],
        state_schema=DecisionDSTState,
        checkpointer=checkpointer,
        debug=settings.environment == "development",
        name="ai_decision_main_agent",
    )
