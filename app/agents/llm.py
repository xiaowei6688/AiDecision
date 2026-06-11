from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    """构建Agent和SubAgents模型."""

    return ChatOpenAI(
        model=settings.agent_model,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=settings.openai_temperature,
        timeout=settings.openai_timeout_seconds,
        streaming=True,
        stream_usage=True,
        extra_body={'enable_thinking': False},
    )
