import hashlib
from dataclasses import dataclass

CHUNKER_VERSION = "char-window-v1"


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ChunkingFailure(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class TextChunk:
    position: int
    start_offset: int
    end_offset: int
    text: str
    sha256: str


def chunk_text(
    text: str, *, max_chars: int, overlap_chars: int, max_count: int
) -> list[TextChunk]:
    """Slice exact source text using zero-based Unicode character offsets."""
    if max_chars < 1 or not 0 <= overlap_chars < max_chars or max_count < 1:
        raise ValueError("Invalid chunking policy.")
    if not text.strip():
        raise ChunkingFailure("CHUNK_SOURCE_EMPTY")
    step = max_chars - overlap_chars
    count = 1 + max(0, (len(text) - max_chars + step - 1) // step)
    if count > max_count:
        raise ChunkingFailure("CHUNK_LIMIT_EXCEEDED")
    chunks = []
    for position in range(count):
        start = position * step
        end = min(start + max_chars, len(text))
        content = text[start:end]
        chunks.append(TextChunk(position, start, end, content, text_digest(content)))
    return chunks
