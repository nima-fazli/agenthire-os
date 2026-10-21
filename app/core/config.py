from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.local_model_origin import local_base_url


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

    extraction_max_pages: int = Field(default=100, ge=1, le=500)
    extraction_max_text_bytes: int = Field(default=1_000_000, ge=1024, le=5_000_000)
    extraction_timeout_seconds: int = Field(default=20, ge=1, le=120)
    extraction_process_memory_mb: int = Field(default=256, ge=64, le=1024)
    extraction_lease_seconds: int = Field(default=60, ge=10, le=600)
    extraction_max_attempts: int = Field(default=3, ge=1, le=10)
    extraction_poll_seconds: float = Field(default=1, ge=0.1, le=30)

    chunk_max_chars: int = Field(default=1200, ge=256, le=4000)
    chunk_overlap_chars: int = Field(default=150, ge=0, le=1000)
    chunk_max_count: int = Field(default=1000, ge=1, le=5000)
    document_search_timeout_ms: int = Field(default=1500, ge=100, le=10000)

    agents_enabled: bool = False
    agent_model: str = Field(default="qwen3:4b", min_length=1, max_length=100)
    agent_num_threads: int = Field(default=4, ge=1, le=16)
    agent_max_steps: int = Field(default=16, ge=4, le=40)
    agent_max_tokens: int = Field(default=24000, ge=2000, le=100000)
    agent_max_elapsed_seconds: int = Field(default=600, ge=30, le=3600)
    agent_timeout_seconds: int = Field(default=120, ge=5, le=180)
    agent_lease_seconds: int = Field(default=240, ge=60, le=600)
    agent_mail_host: Literal["127.0.0.1", "localhost", "mailpit"] = "127.0.0.1"
    agent_mail_port: int = Field(default=1025, ge=1, le=65535)

    @model_validator(mode="after")
    def require_agent_lease_margin(self) -> Self:
        if self.agent_lease_seconds < self.agent_timeout_seconds + 30:
            raise ValueError("Agent lease must cover inference and model identity checks.")
        return self

    explanations_enabled: bool = False
    chat_base_url: str = "http://127.0.0.1:11434"
    chat_timeout_seconds: int = Field(default=120, ge=5, le=180)

    @field_validator("chat_base_url")
    @classmethod
    def require_local_chat_url(cls, value: str) -> str:
        return local_base_url(value)

    semantic_enabled: bool = False
    embedding_base_url: str = "http://127.0.0.1:11434"
    embedding_timeout_seconds: int = Field(default=60, ge=5, le=120)
    embedding_lease_seconds: int = Field(default=300, ge=30, le=600)
    embedding_batch_size: int = Field(default=4, ge=1, le=8)
    embedding_max_attempts: int = Field(default=3, ge=1, le=10)

    @field_validator("embedding_base_url")
    @classmethod
    def require_local_embedding_url(cls, value: str) -> str:
        return local_base_url(value)

    @model_validator(mode="after")
    def require_embedding_lease_margin(self) -> Self:
        if self.embedding_lease_seconds < 3 * self.embedding_timeout_seconds + 30:
            raise ValueError("Embedding lease must cover model checks and inference with a 30-second margin.")
        return self

    @model_validator(mode="after")
    def require_chunk_progress(self) -> Self:
        if self.chunk_overlap_chars >= self.chunk_max_chars:
            raise ValueError("Chunk overlap must be smaller than the chunk size.")
        return self

    @model_validator(mode="after")
    def require_extraction_lease_margin(self) -> Self:
        if self.extraction_lease_seconds < self.extraction_timeout_seconds + 10:
            raise ValueError(
                "Extraction lease must exceed the parser timeout by at least 10 seconds."
            )
        return self

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
