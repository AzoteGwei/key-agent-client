"""What the client does with what the server says — and what it never says on its own."""

from __future__ import annotations

import pytest
from conftest import FakeServer, once

from keyclient import KeyClient
from keyclient.exceptions import TaskTimeoutError


def client(fake: FakeServer) -> KeyClient:
    return KeyClient("127.0.0.1", fake.port, timeout=5)


def test_a_succeeded_task_is_not_a_closed_proof(fake: FakeServer) -> None:
    fake.answer(
        "task.get",
        {
            "taskId": "task-1",
            "kind": "AUTO",
            "status": "SUCCEEDED",
            "result": {"outcome": "COMPLETED", "statistics": {"closed": False, "openGoals": 3}},
        },
    )

    task = client(fake).task("task-1")

    # The distinction the whole project turns on. The work finished; nothing was proved.
    assert task.succeeded is True
    assert task.finished is True
    assert task.statistics.closed is False
    assert task.statistics.open_goals == 3


def test_statistics_come_from_the_server_and_are_never_defaulted(fake: FakeServer) -> None:
    fake.answer("proof.getStatistics", {"openGoals": 2, "nodes": 10})

    statistics = client(fake).statistics("prf-1")

    # A payload with no "closed" field must not become a closed proof by omission.
    assert statistics.closed is False
    assert statistics.open_goals == 2


def test_waiting_polls_until_the_task_is_finished(fake: FakeServer) -> None:
    fake.answer(
        "task.get",
        once(
            {"taskId": "task-1", "kind": "LOAD", "status": "PENDING"},
            {"taskId": "task-1", "kind": "LOAD", "status": "RUNNING"},
            {
                "taskId": "task-1",
                "kind": "LOAD",
                "status": "SUCCEEDED",
                "result": {"envId": "env-1"},
            },
        ),
    )

    task = client(fake).wait_for_task("task-1", poll_interval=0.01)

    assert task.status == "SUCCEEDED"
    assert task.result == {"envId": "env-1"}
    assert len(fake.calls) == 3


def test_waiting_gives_up_without_cancelling_anything(fake: FakeServer) -> None:
    fake.answer("task.get", {"taskId": "task-1", "kind": "AUTO", "status": "RUNNING"})

    with pytest.raises(TaskTimeoutError) as raised:
        client(fake).wait_for_task("task-1", poll_interval=0.01, timeout=0.05)

    # Giving up on waiting is not the same as stopping the work, and the client must not decide
    # to stop a proof search nobody asked it to stop.
    assert raised.value.task_id == "task-1"
    assert "not been cancelled" in str(raised.value)
    assert not any(method == "task.cancel" for method, _ in fake.calls)


def test_the_bare_task_call_stays_available_next_to_the_waiting_one(fake: FakeServer) -> None:
    fake.answer("task.get", {"taskId": "task-1", "kind": "AUTO", "status": "RUNNING"})

    task = client(fake).task("task-1")

    assert task.finished is False
    assert len(fake.calls) == 1


def test_obligations_leave_out_library_contracts_unless_asked(fake: FakeServer) -> None:
    fake.answer("environment.listProofObligations", [])

    with client(fake) as key:
        key.obligations("env-1")
        key.obligations("env-1", include_library_classes=True)

    assert fake.calls[0][1] == {"env": {"envId": "env-1"}}
    assert fake.calls[1][1] == {"env": {"envId": "env-1"}, "includeLibraryClasses": True}


def test_an_empty_stuck_point_list_is_preserved_as_a_finding(fake: FakeServer) -> None:
    fake.answer(
        "diagnostics.listStuckPoints",
        [{"goalId": 30, "stuckPoints": [], "truncated": False}],
    )

    per_goal = client(fake).stuck_points("prf-1")

    # No rule is waiting on anything: the goal is not under-specified. That is information, and
    # the client must not smooth it away into "nothing to report".
    assert len(per_goal) == 1
    assert per_goal[0].stuck_points == []
    assert per_goal[0].truncated is False


def test_an_empty_list_means_two_different_things(fake: FakeServer) -> None:
    fake.answer(
        "diagnostics.listStuckPoints",
        [
            {"goalId": 1, "stuckPoints": [], "truncated": False, "lastSearchOutcome": "EXHAUSTED"},
            {"goalId": 2, "stuckPoints": [], "truncated": False, "lastSearchOutcome": "MAX_RULES"},
            {"goalId": 3, "stuckPoints": [], "truncated": False},
        ],
    )

    spent, cut_short, never_run = client(fake).stuck_points("prf-1")

    # Same empty list, opposite problems: one needs a script or a solver, the other just needs a
    # bigger budget. Collapsing them would send a caller off doing the wrong work.
    assert spent.prover_out_of_ideas is True
    assert cut_short.prover_out_of_ideas is False
    # And a search that never ran establishes neither.
    assert never_run.last_search_outcome is None
    assert never_run.prover_out_of_ideas is False


def test_a_missing_invariant_keeps_its_source_position(fake: FakeServer) -> None:
    fake.answer(
        "diagnostics.explainGoal",
        {
            "goalId": 18,
            "truncated": False,
            "stuckPoints": [
                {
                    "ruleId": "WhileInvariantRule",
                    "ruleName": "Loop Invariant",
                    "positionHint": "loop at Summer.java:26",
                    "reason": "NEEDS_SPEC",
                    "source": {"file": "Summer.java", "line": 26, "column": 9},
                }
            ],
        },
    )

    diagnostics = client(fake).explain_goal("prf-1", 18)

    point = diagnostics.stuck_points[0]
    assert point.needs_specification is True
    assert point.source["line"] == 26


def test_pruning_reports_what_it_removed(fake: FakeServer) -> None:
    fake.answer(
        "proof.prune",
        {
            "goal": {"proofId": "prf-1", "goalId": 0},
            "removedNodes": 26,
            "statistics": {"closed": False, "openGoals": 1, "nodes": 1},
        },
    )

    pruned = client(fake).prune("prf-1", 0)

    # The count matters: KeY answers "nothing to do" and "done" in ways that look alike, so a
    # caller has to be able to see that something actually came off.
    assert pruned.removed_nodes == 26
    assert pruned.goal_id == 0
    assert pruned.statistics.closed is False


def test_the_client_is_a_context_manager(fake: FakeServer) -> None:
    fake.answer("server.health", {"ok": True})

    with KeyClient("127.0.0.1", fake.port) as key:
        assert key.health() is True


def test_events_arrive_as_parsed_notifications(fake: FakeServer) -> None:
    fake.events = [
        '{"jsonrpc":"2.0","method":"task.progress","params":{"taskId":"task-1"}}',
        '{"jsonrpc":"2.0","method":"task.finished","params":{"taskId":"task-1"}}',
    ]

    received = list(client(fake).events())

    assert [each["method"] for each in received] == ["task.progress", "task.finished"]
