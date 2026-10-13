import hashlib
import json
import math
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.types import UserDefinedType

MODEL_TAG = "qwen3-embedding:0.6b"
DIMENSIONS = 1024
ENCODING_VERSION = "qwen3-raw-l2-v1"
MAX_CHUNKS = 1000
MAX_TEXT_CHARS = 4000


class EmbeddingFailure(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def local_base_url(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1", "ollama"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.port != 11434
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError("Embedding URL must point directly to local Ollama port 11434.")
    return value.rstrip("/")


@dataclass(frozen=True)
class ModelIdentity:
    digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.digest, str) or not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise EmbeddingFailure("EMBEDDING_MODEL_IDENTITY_INVALID")


@dataclass(frozen=True)
class SourceChunk:
    position: int
    text: str
    sha256: str


def validate_chunks(chunks: tuple[SourceChunk, ...], expected: int) -> None:
    if not 1 <= expected <= MAX_CHUNKS or len(chunks) != expected:
        raise EmbeddingFailure("EMBEDDING_SOURCE_INVALID")
    for position, chunk in enumerate(chunks):
        if (
            chunk.position != position
            or not 1 <= len(chunk.text) <= MAX_TEXT_CHARS
            or hashlib.sha256(chunk.text.encode("utf-8")).hexdigest() != chunk.sha256
        ):
            raise EmbeddingFailure("EMBEDDING_SOURCE_INVALID")


def normalized_vector(value) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != DIMENSIONS:
        raise EmbeddingFailure("EMBEDDING_VECTOR_INVALID")
    try:
        if any(type(item) not in {float, int} or not math.isfinite(item) for item in value):
            raise EmbeddingFailure("EMBEDDING_VECTOR_INVALID")
        norm = math.hypot(*value)
    except (OverflowError, TypeError) as error:
        raise EmbeddingFailure("EMBEDDING_VECTOR_INVALID") from error
    if not math.isfinite(norm) or norm <= 1e-12:
        raise EmbeddingFailure("EMBEDDING_VECTOR_INVALID")
    return tuple(float(item) / norm for item in value)


class EmbeddingVector(UserDefinedType):
    """Text transport for PostgreSQL vector; no extra Python package required."""

    cache_ok = True

    def __init__(self, dimensions: int | str | None = None) -> None:
        self.dimensions = None if dimensions is None else int(dimensions)

    def get_col_spec(self, **kwargs) -> str:
        return "vector" if self.dimensions is None else f"vector({self.dimensions})"

    def bind_processor(self, dialect):
        def encode(value):
            if value is None:
                return None
            return json.dumps(normalized_vector(value), allow_nan=False, separators=(",", ":"))

        return encode

    def result_processor(self, dialect, coltype):
        def decode(value):
            return None if value is None else tuple(json.loads(value))

        return decode


# Alembic must reflect vector dimensions instead of treating the column as unknown.
ischema_names["vector"] = EmbeddingVector
