import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts.ci_execution import Result, execute_plan, execute_step, summary
from scripts.ci_plan import Step


def test_real_child_exit_is_preserved_without_shell(tmp_path):
    step = Step("child", (sys.executable, "-c", "raise SystemExit(7)"))
    result = execute_step(step, root=tmp_path, environment=os.environ)
    assert result == Result("child", 7)


def test_real_child_timeout_is_bounded(tmp_path):
    step = Step("slow", (sys.executable, "-c", "import time; time.sleep(2)"), 0.05)
    assert execute_step(step, root=tmp_path, environment=os.environ).code == 124


@pytest.mark.parametrize(
    "error,code",
    [
        (OSError("private-secret-value"), 127),
        (subprocess.TimeoutExpired("private-secret-value", 3), 124),
    ],
    ids=["start-error", "timeout"],
)
def test_process_errors_do_not_echo_private_details(error, code, tmp_path, capsys):
    def run(*args, **kwargs):
        raise error

    result = execute_step(
        Step("safe", ("unused",)), root=tmp_path, environment={}, runner=run
    )
    assert result.code == code
    assert "private-secret-value" not in capsys.readouterr().out


def test_failure_stops_following_steps_and_preserves_code_after_cleanup(tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command[0])
        assert "shell" not in kwargs
        assert kwargs["stdin"] == subprocess.DEVNULL
        return SimpleNamespace(returncode={"first": 9, "cleanup": 2}[command[0]])

    code, results = execute_plan(
        [Step("first", ("first",)), Step("later", ("later",))],
        Step("cleanup", ("cleanup",)),
        root=tmp_path,
        environment={},
        runner=run,
    )
    assert calls == ["first", "cleanup"]
    assert code == 9
    assert [x.code for x in results] == [9, 2]


def test_cleanup_failure_prevents_success(tmp_path):
    def run(command, **kwargs):
        return SimpleNamespace(returncode=3 if command == ("cleanup",) else 0)

    code, results = execute_plan(
        [Step("first", ("first",))],
        Step("cleanup", ("cleanup",)),
        root=tmp_path,
        environment={},
        runner=run,
    )
    assert code == 3
    assert "**FAILED**" in summary(results, passed=code == 0)


def test_interrupt_still_attempts_cleanup(tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command[0])
        if command == ("first",):
            raise KeyboardInterrupt
        return SimpleNamespace(returncode=0)

    code, _ = execute_plan(
        [Step("first", ("first",))],
        Step("cleanup", ("cleanup",)),
        root=tmp_path,
        environment={},
        runner=run,
    )
    assert code == 130
    assert calls == ["first", "cleanup"]


def test_unexpected_error_still_attempts_cleanup(tmp_path):
    calls = []

    def run(command, **kwargs):
        calls.append(command[0])
        if command == ("first",):
            raise RuntimeError("test runner error")
        return SimpleNamespace(returncode=0)

    with pytest.raises(RuntimeError):
        execute_plan(
            [Step("first", ("first",))],
            Step("cleanup", ("cleanup",)),
            root=tmp_path,
            environment={},
            runner=run,
        )
    assert calls == ["first", "cleanup"]


def test_signal_exit_cannot_turn_into_success(tmp_path):
    result = execute_step(
        Step("killed", ("unused",)),
        root=tmp_path,
        environment={},
        runner=lambda *args, **kwargs: SimpleNamespace(returncode=-15),
    )
    assert result.code == 143
