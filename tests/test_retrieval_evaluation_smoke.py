from unittest.mock import AsyncMock

import pytest

from app.services.retrieval_evaluation import RetrievalEvaluationService
from scripts import retrieval_evaluation_smoke
from scripts.docker_smoke import SmokeFailure
from scripts.evaluation_cases import load_example, load_suite


@pytest.mark.parametrize(
    "mode", ["success", "quality-failure", "server-failure", "example"]
)
def test_smoke_always_cleans_its_unique_fixture_and_never_certifies_failed_or_example_data(
    mode, monkeypatch, capsys
):
    report = (
        RetrievalEvaluationService()
        .evaluate(load_suite(), load_example())
        .model_copy(update={"source_kind": "real_stack"})
    )
    if mode == "quality-failure":
        report = report.model_copy(update={"gate_passed": False})
    elif mode == "example":
        report = report.model_copy(update={"source_kind": "example"})
    seen = []

    def run(slugs, emails):
        seen.append((slugs, emails))
        if mode == "server-failure":
            raise SmokeFailure("synthetic server failure")
        return report

    cleanup = AsyncMock()
    monkeypatch.setattr(retrieval_evaluation_smoke, "run", run)
    monkeypatch.setattr(retrieval_evaluation_smoke, "cleanup_retrieval", cleanup)
    if mode == "success":
        retrieval_evaluation_smoke.main()
    else:
        with pytest.raises(SmokeFailure):
            retrieval_evaluation_smoke.main()
    cleanup.assert_awaited_once_with(*seen[0])
    assert seen[0][0][0].startswith("quality-smoke-") and seen[0][0][1].startswith(
        "quality-other-"
    )
    assert ("[success]" in capsys.readouterr().out) == (mode == "success")
