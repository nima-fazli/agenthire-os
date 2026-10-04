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


def test_settings_read_prefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENTHIRE_ENVIRONMENT", "test")
    monkeypatch.setenv("AGENTHIRE_DEBUG", "true")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.debug is True


def test_settings_reject_invalid_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(
            environment="invalid",
            _env_file=None,
        )
