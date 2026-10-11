from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="AGENTHIRE_",
        extra="ignore",
        hide_input_in_errors=True,
    )

    app_name: str = "AgentHire OS API"
    app_version: str = "0.1.0"
    environment: Literal["local", "test", "staging", "production"] = "local"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    postgres_host: str = "127.0.0.1"
    postgres_port: int = Field(default=5435, ge=1, le=65535)
    postgres_db: str = "agenthire"
    postgres_user: str = "agenthire"
    postgres_password: SecretStr = Field(default=SecretStr("change-me"), min_length=1)

    jwt_secret: SecretStr = Field(
        default=SecretStr("change-me-with-a-secure-random-secret"), min_length=1
    )
    jwt_algorithm: Literal["HS256"] = "HS256"
    access_token_expire_minutes: int = Field(default=30, gt=0)

    document_storage_path: Path = Path("storage/candidate_documents")
    document_max_bytes: int = Field(
        default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024
    )
    document_upload_timeout_seconds: int = Field(default=60, ge=1, le=300)

    @field_validator("document_storage_path", mode="before")
    @classmethod
    def require_dedicated_storage_directory(cls, value: str | Path) -> Path:
        path = Path(value)
        if not str(value).strip() or not path.name or path.name == "..":
            raise ValueError("Document storage requires a dedicated directory.")
        return path

    @model_validator(mode="after")
    def require_safe_deployment_settings(self) -> Self:
        if self.environment not in {"staging", "production"}:
            return self

        if self.debug:
            raise ValueError("Debug must be disabled in staging and production.")

        jwt_secret = self.jwt_secret.get_secret_value()
        if (
            jwt_secret.strip().lower()
            in {"change-me", "change-me-with-a-secure-random-secret"}
            or len(jwt_secret.encode("utf-8")) < 32
            or not jwt_secret.strip()
        ):
            raise ValueError(
                "Staging and production require a non-placeholder JWT secret of at least 32 bytes."
            )

        postgres_password = self.postgres_password.get_secret_value()
        if (
            not postgres_password.strip()
            or postgres_password.strip().lower() == "change-me"
        ):
            raise ValueError(
                "Staging and production require a non-placeholder database password."
            )

        return self


def get_settings() -> Settings:
    return Settings()
