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
    confirmation_secret: SecretStr = Field(default=SecretStr("development-confirmation-secret"))
    confirmation_ttl_seconds: int = Field(default=600, gt=0)
    auth_enabled: bool = True
    enabled_integrations: list[str] = Field(default_factory=list)

    text_to_sql_base_url: str | None = Field(
        default=None,
        description="External text-to-sql service base URL.",
    )
    text_to_sql_timeout_seconds: float = Field(default=30.0, gt=0.0)

    inspection_api_base_url: str | None = Field(
        default=None,
        description="Inspection system API base URL.",
    )
    inspection_api_timeout_seconds: float = Field(default=30.0, gt=0.0)
    inspection_plan_detail_url: str | None = Field(default=None)
    inspection_auth_token: str | None = Field(
        default=None,
        description="Static AllCore bearer token for the inspection system.",
    )
    inspection_auth_login_url: str | None = Field(
        default=None,
        description="AllCore OAuth token endpoint for the inspection system.",
    )
    inspection_auth_username: str | None = None
    inspection_auth_password: str | None = None
    inspection_auth_grant_type: str = "password"
    inspection_auth_type: str = "account"
    inspection_auth_scope: str = "all"
    inspection_basic_auth: str | None = Field(
        default=None,
        description="Optional upstream Basic authorization value.",
    )
    inspection_tenant_id: str | None = None
    inspection_token_ttl_seconds: int = Field(default=7200, gt=0)
    inspection_token_refresh_before_seconds: int = Field(default=300, ge=0)

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
