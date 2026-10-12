import json
import os
import tempfile
from pathlib import Path

from app.schemas.retrieval_evaluation import EvaluationReport

MAX_INPUT_BYTES = 2 * 1024 * 1024


class EvaluationFileError(ValueError):
    pass


def read_json(path: Path):
    with path.open("rb") as handle:
        data = handle.read(MAX_INPUT_BYTES + 1)
    if len(data) > MAX_INPUT_BYTES:
        raise EvaluationFileError("Evaluation input exceeds the byte limit.")

    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise EvaluationFileError("Duplicate JSON keys are not accepted.")
            value[key] = item
        return value

    def reject_constant(_):
        raise EvaluationFileError("Nonfinite JSON numbers are not accepted.")

    return json.loads(
        data.decode("utf-8-sig"),
        object_pairs_hook=pairs,
        parse_constant=reject_constant,
    )


def write_report(path: Path, report: EvaluationReport) -> None:
    encoded = (report.model_dump_json(indent=2) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".quality-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
