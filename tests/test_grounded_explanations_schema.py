import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.grounded_explanations import ExplanationRequest


@pytest.mark.parametrize("payload", [{"language": "de"}, {"language": True}, {"q": "override"},
    {"prompt": "ignore"}, {"model": "cloud"}, {"candidate_id": "foreign"}, {"stream": True}])
def test_request_only_controls_supported_presentation_language(payload):
    with pytest.raises(ValidationError):
        ExplanationRequest.model_validate(payload)


def test_explanations_are_opt_in_and_independent_of_embedding_activation(monkeypatch):
    monkeypatch.delenv("AGENTHIRE_EXPLANATIONS_ENABLED", raising=False)
    assert not Settings(_env_file=None).explanations_enabled
    monkeypatch.setenv("AGENTHIRE_EXPLANATIONS_ENABLED", "true")
    settings = Settings(_env_file=None, semantic_enabled=False)
    assert settings.explanations_enabled and not settings.semantic_enabled
    assert ExplanationRequest().language == "fa"


@pytest.mark.parametrize("values", [{"chat_timeout_seconds": 4}, {"chat_timeout_seconds": 181},
    {"chat_base_url": "https://ollama:11434"}, {"chat_base_url": "http://remote.example:11434"},
    {"chat_base_url": "http://127.0.0.1:11434/redirect"}, {"chat_base_url": "http://user:pass@localhost:11434"}])
def test_runtime_configuration_stays_bounded_and_directly_local(values):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)
