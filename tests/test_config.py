import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_defaults() -> None:
    settings = Settings(
        _env_file=None,
    )

    assert settings.app_name == "AgentHire OS API"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "local"
    assert settings.debug is False
    assert settings.log_level == "INFO"

    assert settings.postgres_host == "127.0.0.1"
    assert settings.postgres_port == 5435
    assert settings.postgres_db == "agenthire"
    assert settings.postgres_user == "agenthire"

    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 30


def test_settings_read_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AGENTHIRE_APP_NAME",
        "Test API",
    )
    monkeypatch.setenv(
        "AGENTHIRE_ENVIRONMENT",
        "test",
    )
    monkeypatch.setenv(
        "AGENTHIRE_POSTGRES_PORT",
        "6543",
    )
    monkeypatch.setenv(
        "AGENTHIRE_JWT_SECRET",
        "test-jwt-secret",
    )
    monkeypatch.setenv(
        "AGENTHIRE_ACCESS_TOKEN_EXPIRE_MINUTES",
        "45",
    )

    settings = Settings(
        _env_file=None,
    )

    assert settings.app_name == "Test API"
    assert settings.environment == "test"
    assert settings.postgres_port == 6543

    assert (
        settings.jwt_secret.get_secret_value()
        == "test-jwt-secret"
    )
    assert settings.access_token_expire_minutes == 45


def test_settings_reject_invalid_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="invalid",
            _env_file=None,
        )
