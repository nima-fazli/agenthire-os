from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENTHIRE_",
        extra="ignore",
    )

    app_name: str = "AgentHire OS API"
    app_version: str = "0.1.0"
    environment: Literal[
        "local",
        "test",
        "staging",
        "production",
    ] = "local"
    debug: bool = False
    log_level: Literal[
        "DEBUG",
        "INFO",
        "WARNING",
        "ERROR",
        "CRITICAL",
    ] = "INFO"

    postgres_host: str = "127.0.0.1"
    postgres_port: int = 5435
    postgres_db: str = "agenthire"
    postgres_user: str = "agenthire"
    postgres_password: SecretStr = SecretStr(
        "change-me"
    )

    jwt_secret: SecretStr = SecretStr(
        "change-me-with-a-secure-random-secret"
    )
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = 30


def get_settings() -> Settings:
    return Settings()
