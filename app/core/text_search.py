import re
import unicodedata

from sqlalchemy import func, literal_column
from sqlalchemy.sql.elements import ColumnElement

SEARCH_VERSION = "simple-fold-v1"
SEARCH_INDEX = "ix_document_chunks_search_v1"
LATEST_SET_INDEX = "ix_document_chunk_sets_latest"
REGCONFIG = literal_column("'simple'::regconfig")


def validate_search_query(value: str) -> str:
    if any(
        unicodedata.category(char) in {"Cc", "Cs"} and char not in "\n\r\t"
        for char in value
    ):
        raise ValueError("Search query contains unsupported control characters.")
    value = value.strip()
    normalized = unicodedata.normalize("NFKC", value).replace("\u0640", "")
    normalized = re.sub(r"[\u064B-\u065F\u0670\u06D6-\u06ED]", "", normalized)
    terms = re.findall(r"[^\W_]+", normalized, flags=re.UNICODE)
    if not any(char.isalnum() for char in normalized):
        raise ValueError("Search query must contain a word or number.")
    if len(normalized) > 256 or len(terms) > 16:
        raise ValueError("Search query exceeds the size or term limit.")
    return value


def search_vector(column: ColumnElement):
    return func.to_tsvector(REGCONFIG, func.agenthire_search_text_v1(column))


def search_query(value: str):
    return func.plainto_tsquery(REGCONFIG, func.agenthire_search_text_v1(value))
