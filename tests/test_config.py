from app.core.config import Settings
from app.integrations.inspection.config import InspectionSettings


def test_settings_defaults_are_development_friendly() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "AI Decision Service"
    assert settings.environment == "development"
    assert settings.agent_model
    assert settings.auth_enabled is True


def test_framework_settings_do_not_expose_inspection_config() -> None:
    settings = Settings(_env_file=None)

    assert not hasattr(settings, "inspection_plan_detail_url")
    assert not hasattr(settings, "inspection_api_base_url")
    assert not hasattr(settings, "inspection_auth_token")


def test_inspection_settings_are_integration_owned() -> None:
    settings = InspectionSettings(
        _env_file=None,
        plan_detail_url="http://inspection.local/plan/detail",
        auth_token="token",
    )

    assert settings.plan_detail_url == "http://inspection.local/plan/detail"
    assert settings.auth_token == "token"
