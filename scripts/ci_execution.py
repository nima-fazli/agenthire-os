import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from scripts.ci_plan import Step


@dataclass(frozen=True)
class Result:
    name: str
    code: int


def execute_step(
    step: Step,
    *,
    root: Path,
    environment: Mapping[str, str],
    runner: Callable = subprocess.run,
    log: Callable[[str], None] = print,
) -> Result:
    log(f"[run] {step.name}")
    try:
        process = runner(
            step.command,
            cwd=root,
            env=dict(environment),
            check=False,
            timeout=step.timeout,
            stdin=subprocess.DEVNULL,
        )
        code = process.returncode
        if code < 0:
            code = min(255, 128 - code)
    except subprocess.TimeoutExpired:
        code = 124
    except OSError:
        code = 127
    log(f"[{'ok' if code == 0 else 'failed'}] {step.name}: exit {code}")
    return Result(step.name, code)


def summary(results: Sequence[Result], *, passed: bool) -> str:
    rows = [
        "## AgentHire OS real-stack verification",
        "",
        "Result: **PASSED**" if passed else "Result: **FAILED**",
        "",
        "| Check | Exit |",
        "| --- | --- |",
        *(f"| {result.name} | {result.code} |" for result in results),
        "",
    ]
    return "\n".join(rows)


def execute_plan(
    steps: Sequence[Step],
    cleanup: Step,
    *,
    root: Path,
    environment: Mapping[str, str],
    runner: Callable = subprocess.run,
    log: Callable[[str], None] = print,
) -> tuple[int, tuple[Result, ...]]:
    results: list[Result] = []
    code = 0
    try:
        for step in steps:
            result = execute_step(
                step,
                root=root,
                environment=environment,
                runner=runner,
                log=log,
            )
            results.append(result)
            if result.code:
                code = result.code
                break
    except KeyboardInterrupt:
        code = 130
        results.append(Result("interrupted", code))
    finally:
        try:
            cleaned = execute_step(
                cleanup,
                root=root,
                environment=environment,
                runner=runner,
                log=log,
            )
        except KeyboardInterrupt:
            cleaned = Result(cleanup.name, 130)
        results.append(cleaned)
    if code == 0:
        code = cleaned.code
    return code, tuple(results)
