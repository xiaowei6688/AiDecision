from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI Decision Service"
    environment: str = "development"
    log_level: str = "INFO"

    database_url: str | None = Field(
        default=None,
        description="PostgreSQL CheckPoints.",
    )
    checkpoint_setup_on_start: bool = True

    agent_model: str = "gpt-4o-mini"
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    openai_timeout_seconds: float = Field(default=60.0, gt=0.0)
    allowed_origins: list[str] = Field(default_factory=lambda: ["*"])

    context_recent_messages: int = Field(
        default=20,
        ge=4,
        description="每个会话中逐字保存的最新消息数.",
    )
    context_summary_max_chars: int = Field(
        default=6000,
        ge=1000,
        description="摘要保存的最大字数.",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
