from langchain_openai import ChatOpenAI

from app.agents.llm import build_chat_model
from app.core.config import Settings


def test_build_chat_model_returns_chat_openai() -> None:
    settings = Settings(
        _env_file=None,
        agent_model="gpt-4o-mini",
        openai_api_key="test-key",
        openai_temperature=0.1,
        openai_timeout_seconds=30,
    )

    model = build_chat_model(settings)

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-4o-mini"
    assert model.temperature == 0.1


def test_build_chat_model_accepts_openai_compatible_base_url() -> None:
    settings = Settings(
        _env_file=None,
        agent_model="gpt-4o-mini",
        openai_api_key="test-key",
        openai_base_url="https://gateway.example.com/v1",
    )

    model = build_chat_model(settings)

    assert isinstance(model, ChatOpenAI)
