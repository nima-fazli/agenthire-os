import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_defaults() -> None:
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
    assert settings.jwt_algorithm == "HS256"
    assert settings.access_token_expire_minutes == 30


def test_settings_read_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTHIRE_APP_NAME", "Test API")
    monkeypatch.setenv("AGENTHIRE_ENVIRONMENT", "test")
    monkeypatch.setenv("AGENTHIRE_POSTGRES_PORT", "6543")
    monkeypatch.setenv("AGENTHIRE_JWT_SECRET", "test-jwt-secret")
    monkeypatch.setenv("AGENTHIRE_ACCESS_TOKEN_EXPIRE_MINUTES", "45")

    settings = Settings(_env_file=None)

    assert settings.app_name == "Test API"
    assert settings.environment == "test"
    assert settings.postgres_port == 6543
    assert settings.jwt_secret.get_secret_value() == "test-jwt-secret"
    assert settings.access_token_expire_minutes == 45


def test_settings_reject_invalid_environment() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="invalid", _env_file=None)


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_settings_accept_explicit_secrets(environment: str) -> None:
    settings = Settings(
        _env_file=None,
        environment=environment,
        jwt_secret="synthetic-test-key-with-at-least-32-bytes",
        postgres_password="synthetic-database-password",
    )

    assert settings.debug is False
    assert settings.environment == environment


@pytest.mark.parametrize("environment", ["staging", "production"])
def test_deployed_settings_reject_debug(environment: str) -> None:
    with pytest.raises(ValidationError, match="Debug must be disabled"):
        Settings(
            _env_file=None,
            environment=environment,
            debug=True,
            jwt_secret="synthetic-test-key-with-at-least-32-bytes",
            postgres_password="synthetic-database-password",
        )


@pytest.mark.parametrize(
    "secret", ["change-me-with-a-secure-random-secret", "short-test-key", " " * 40]
)
def test_production_rejects_insecure_jwt_secret(secret: str) -> None:
    with pytest.raises(ValidationError, match="non-placeholder JWT secret"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret=secret,
            postgres_password="synthetic-database-password",
        )


@pytest.mark.parametrize("password", ["change-me", " " * 8])
def test_production_rejects_insecure_database_password(password: str) -> None:
    with pytest.raises(ValidationError, match="non-placeholder database password"):
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret="synthetic-test-key-with-at-least-32-bytes",
            postgres_password=password,
        )


@pytest.mark.parametrize("minutes", [0, -1])
def test_settings_reject_non_positive_token_lifetime(minutes: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, access_token_expire_minutes=minutes)


@pytest.mark.parametrize("port", [0, -1, 65536])
def test_settings_reject_invalid_database_port(port: int) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, postgres_port=port)


def test_settings_validation_message_does_not_echo_secret_values() -> None:
    secret = "synthetic-private-canary"
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            environment="production",
            jwt_secret=secret,
            postgres_password="synthetic-database-password",
        )

    assert secret not in str(error.value)
    assert "synthetic-database-password" not in str(error.value)
