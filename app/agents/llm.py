from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import Settings


def build_chat_model(settings: Settings) -> BaseChatModel:
    """构建Agent和SubAgents模型."""

    _validate_openai_compatible_settings(settings)
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


def _validate_openai_compatible_settings(settings: Settings) -> None:
    base_url = settings.openai_base_url or ""
    model = settings.agent_model.lower()
    if "aliyuncs.com" in base_url and "/compatible-mode/v1" not in base_url:
        raise ValueError(
            "阿里云百炼模型需要使用 OpenAI 兼容地址，"
            "请把 OPENAI_BASE_URL 配成 https://...aliyuncs.com/compatible-mode/v1"
        )
    if model.startswith("qwen") and base_url == "https://api.openai.com/v1":
        raise ValueError(
            "qwen 模型不能使用 OpenAI 官方 OPENAI_BASE_URL，"
            "请配置对应供应商的 OpenAI 兼容地址。"
        )
