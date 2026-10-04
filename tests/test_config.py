import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_use_expected_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.app_name == "AgentHire OS API"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "local"
    assert settings.debug is False
    assert settings.log_level == "INFO"

    assert settings.postgres_host == "127.0.0.1"
    assert settings.postgres_port == 5435
    assert settings.postgres_db == "agenthire"
    assert settings.postgres_user == "agenthire"
    assert settings.postgres_password.get_secret_value() == "change-me"


def test_settings_read_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTHIRE_ENVIRONMENT", "test")
    monkeypatch.setenv("AGENTHIRE_DEBUG", "true")
    monkeypatch.setenv("AGENTHIRE_POSTGRES_PORT", "6000")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.debug is True
    assert settings.postgres_port == 6000


def test_settings_reject_invalid_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="invalid",
            _env_file=None,
        )
