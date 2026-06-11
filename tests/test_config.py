from app.core.config import Settings


def test_settings_defaults_are_development_friendly() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "AI Decision Service"
    assert settings.environment == "development"
    assert settings.agent_model
