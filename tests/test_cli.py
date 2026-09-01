"""The command line's two contracts: what the exit status means, and what lands on stdout."""

from __future__ import annotations

import json

from conftest import FakeServer, once

from keyclient.cli import EXIT_CLOSED, EXIT_FAILED, EXIT_NOT_CLOSED, main
from keyclient.exceptions import ErrorCode


def run(fake: FakeServer, *args: str) -> int:
    return main(["--port", str(fake.port), *args])


def _proof_that(fake: FakeServer, *, closed: bool) -> None:
    fake.answer("proof.start", {"proofId": "prf-1"})
    fake.answer("proof.runAuto", {"taskId": "task-1", "kind": "AUTO", "status": "PENDING"})
    fake.answer(
        "task.get",
        {
            "taskId": "task-1",
            "kind": "AUTO",
            "status": "SUCCEEDED",
            "result": {"outcome": "COMPLETED", "statistics": {"closed": closed}},
        },
    )
    fake.answer("proof.getStatistics", {"closed": closed, "openGoals": 0 if closed else 2})


def test_a_closed_proof_exits_zero(fake: FakeServer, capsys) -> None:
    _proof_that(fake, closed=True)

    assert run(fake, "prove", "env-1", "contract") == EXIT_CLOSED
    assert "closed\ttrue" in capsys.readouterr().out


def test_an_open_proof_exits_one_and_is_not_a_failure(fake: FakeServer, capsys) -> None:
    _proof_that(fake, closed=False)

    # One is the whole point of the scheme. A caller that treats every non-zero status as a
    # broken tool will report unproved code as a crash, so the two have to be different numbers.
    assert run(fake, "prove", "env-1", "contract") == EXIT_NOT_CLOSED
    output = capsys.readouterr().out
    assert "closed\tfalse" in output
    assert "openGoals\t2" in output


def test_a_refused_request_exits_two(fake: FakeServer, capsys) -> None:
    fake.fail("proof.start", ErrorCode.INVALID_PARAMS, "No such contract")

    assert run(fake, "prove", "env-1", "nope") == EXIT_FAILED
    captured = capsys.readouterr()
    assert "No such contract" in captured.err
    assert captured.out == ""


def test_a_task_that_failed_exits_two_and_reports_where(fake: FakeServer, capsys) -> None:
    fake.answer("environment.load", {"taskId": "task-1", "kind": "LOAD", "status": "PENDING"})
    fake.answer(
        "task.get",
        {
            "taskId": "task-1",
            "kind": "LOAD",
            "status": "FAILED",
            "error": {
                "detail": "Syntax error",
                "positions": [{"file": "broken.key", "line": 7, "column": 1, "message": "boom"}],
            },
        },
    )

    assert run(fake, "load", "/tmp/x") == EXIT_FAILED
    assert "broken.key:7:1" in capsys.readouterr().err


def test_json_mode_writes_one_object_and_nothing_else(fake: FakeServer, capsys) -> None:
    _proof_that(fake, closed=False)

    status = run(fake, "--json", "prove", "env-1", "contract")

    captured = capsys.readouterr()
    # Exactly one document, parseable without stripping anything: no banner, no progress line,
    # no trailing note. A pipe has to stay a pipe.
    payload = json.loads(captured.out)
    assert payload["statistics"]["closed"] is False
    assert captured.out.count("\n") == 1
    assert status == EXIT_NOT_CLOSED
    # Progress and advice still happen, on the other stream.
    assert "task\ttask-1" in captured.err


def test_json_mode_still_produces_an_object_when_the_call_fails(fake: FakeServer, capsys) -> None:
    fake.fail("proof.getStatistics", ErrorCode.PROOF_NOT_FOUND, "No such proof")

    assert run(fake, "--json", "status", "prf-gone") == EXIT_FAILED

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["error"]["code"] == ErrorCode.PROOF_NOT_FOUND
    assert "No such proof" in captured.err


def test_human_output_is_lines_a_program_can_grep(fake: FakeServer, capsys) -> None:
    fake.answer(
        "environment.listProofObligations",
        [
            {
                "contractId": "Max[Max::max(int,int)].JML normal_behavior operation contract.0",
                "kind": "FUNCTIONAL_OPERATION",
                "targetClass": "Max",
                "targetMember": "max(int, int)",
                "hasExistingProof": False,
            }
        ],
    )

    assert run(fake, "obligations", "env-1") == EXIT_CLOSED

    output = capsys.readouterr().out
    assert output.startswith("Max\tmax(int, int)\tFUNCTIONAL_OPERATION\topen\t")
    # No borders, no colour, no spinner: one record per line, fields separated by tabs.
    assert "│" not in output and "\x1b[" not in output
    assert len(output.strip().splitlines()) == 1


def test_explain_says_plainly_when_nothing_is_waiting_on_a_specification(
    fake: FakeServer, capsys
) -> None:
    fake.answer(
        "diagnostics.listStuckPoints",
        [{"goalId": 30, "stuckPoints": [], "truncated": False}],
    )

    assert run(fake, "explain", "prf-1") == EXIT_CLOSED

    # An empty result must read as a finding, not as an empty listing that says nothing.
    assert "no-rule-applies" in capsys.readouterr().out


def test_no_server_is_reported_with_a_command_that_starts_one(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "empty"))

    assert main(["--workspace", str(tmp_path), "list"]) == EXIT_CLOSED
    assert main(["--workspace", str(tmp_path), "version"]) == EXIT_FAILED

    assert "java -jar" in capsys.readouterr().err


def test_a_stale_record_is_listed_as_stale(tmp_path, monkeypatch, capsys) -> None:
    directory = tmp_path / "state" / "keyext-server" / "instances"
    directory.mkdir(parents=True)
    (directory / "inst-dead.json").write_text(
        json.dumps(
            {
                "instanceId": "inst-dead",
                "pid": 0,
                "host": "127.0.0.1",
                "port": 8899,
                "workspacePath": str(tmp_path),
                "apiVersion": "0.1.0",
                "keyVersion": "3.1.0-dev",
                "threads": 1,
                "startedAt": "2026-09-01T00:00:00Z",
            }
        )
    )
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    assert main(["list"]) == EXIT_CLOSED
    assert "inst-dead\tstale\t" in capsys.readouterr().out


def test_waiting_for_a_slow_task_still_reaches_the_result(fake: FakeServer, capsys) -> None:
    fake.answer("environment.load", {"taskId": "task-1", "kind": "LOAD", "status": "PENDING"})
    fake.answer(
        "task.get",
        once(
            {"taskId": "task-1", "kind": "LOAD", "status": "RUNNING"},
            {
                "taskId": "task-1",
                "kind": "LOAD",
                "status": "SUCCEEDED",
                "result": {"envId": "env-9"},
            },
        ),
    )

    assert run(fake, "load", "/tmp/x") == EXIT_CLOSED
    assert "env\tenv-9" in capsys.readouterr().out
