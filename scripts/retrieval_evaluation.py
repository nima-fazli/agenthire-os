import argparse
import sys
from pathlib import Path

from app.schemas.retrieval_evaluation import EvaluationObservations, EvaluationSuite
from app.services.retrieval_evaluation import (
    EvaluationDataError,
    RetrievalEvaluationService,
)
from scripts.evaluation_cases import EXAMPLE_PATH, SUITE_PATH
from scripts.evaluation_report import EvaluationFileError, read_json, write_report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate reference labels against retrieved results."
    )
    parser.add_argument("--suite", type=Path, default=SUITE_PATH)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--example", action="store_true")
    source.add_argument("--observations", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    observation_path = EXAMPLE_PATH if args.example else args.observations
    try:
        if args.output and args.output.resolve() in {
            args.suite.resolve(),
            observation_path.resolve(),
        }:
            raise EvaluationFileError("The report cannot replace its input files.")
        suite = EvaluationSuite.model_validate(read_json(args.suite))
        observations = EvaluationObservations.model_validate(
            read_json(observation_path)
        )
        if args.example and observations.source_kind != "example":
            raise EvaluationFileError(
                "Example observations must be identified as an example."
            )
        report = RetrievalEvaluationService().evaluate(suite, observations)
        if args.output:
            write_report(args.output, report)
        print(report.model_dump_json(indent=2))
        return 0 if report.gate_passed else 1
    except EvaluationDataError as error:
        print(f"Evaluation data mismatch: {error}", file=sys.stderr)
    except (OSError, ValueError):
        print("Evaluation input or output could not be validated.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
