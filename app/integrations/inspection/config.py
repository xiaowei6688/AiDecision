"""Runtime settings owned by the inspection integration."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class InspectionSettings(BaseSettings):
    """Configuration for the inspection business integration only."""

    model_config = SettingsConfigDict(
        env_file="app/integrations/inspection/.env",
        env_file_encoding="utf-8",
        env_prefix="INSPECTION_",
        extra="ignore",
    )

    api_base_url: str | None = Field(
        default=None,
        description="Inspection system API base URL for integration-owned upstream calls.",
    )
    api_timeout_seconds: float = Field(default=30.0, gt=0.0)
    timezone: str = "Asia/Shanghai"
    plan_detail_url: str | None = Field(default=None)
    drone_list_url: str | None = None
    flight_worker_list_url: str | None = None
    text_to_sql_datasource: str = "inspection_mysql"
    allcore_auth_token: str | None = None
    allcore_auth_login_url: str | None = None
    allcore_auth_username: str | None = None
    allcore_auth_password: str | None = None
    allcore_auth_grant_type: str = "password"
    allcore_auth_type: str = "account"
    allcore_auth_scope: str = "all"
    allcore_basic_auth: str | None = None
    allcore_tenant_id: str | None = None
    allcore_token_ttl_seconds: int = Field(default=7200, gt=0)
    allcore_token_refresh_before_seconds: int = Field(default=300, ge=0)
    allcore_verify_tls: bool = False


@lru_cache
def get_inspection_settings() -> InspectionSettings:
    return InspectionSettings()
