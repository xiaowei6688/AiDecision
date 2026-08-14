from langchain_openai import ChatOpenAI
import pytest

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


def test_build_chat_model_rejects_dashscope_non_compatible_url() -> None:
    settings = Settings(
        _env_file=None,
        agent_model="qwen3-max",
        openai_api_key="test-key",
        openai_base_url="https://workspace.cn-beijing.maas.aliyuncs.com/api/v1",
    )

    with pytest.raises(ValueError, match="OpenAI 兼容地址"):
        build_chat_model(settings)


def test_build_chat_model_rejects_qwen_with_openai_official_url() -> None:
    settings = Settings(
        _env_file=None,
        agent_model="qwen3-max",
        openai_api_key="test-key",
        openai_base_url="https://api.openai.com/v1",
    )

    with pytest.raises(ValueError, match="qwen 模型不能使用 OpenAI 官方"):
        build_chat_model(settings)
