"""What ``examples/first-proof`` actually does, asked of a real server.

Everything else in this suite talks to a fake. This file does not, because the example's whole
job is to be the thing whose answers are known, and a fake that answers `closed: true` because it
was told to would establish nothing about that.

Skipped unless a KeY server is already running; start one and they run::

    java -Xmx4g -jar keyext.server-*-exe.jar --port 0 --workspace examples/first-proof

These are the assertions that hold ``docs/guide.md`` to its promises: the contract ids it prints,
the verdict beside each one, and the two different diagnoses it says you will get.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from keyclient import KeyClient
from keyclient.discovery import list_instances

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "first-proof"

MAX = "Max[Max::max(int,int)].JML normal_behavior operation contract.0"
BROKEN_MAX = "BrokenMax[BrokenMax::max(int,int)].JML normal_behavior operation contract.0"
SUMMER = "Summer[Summer::sumTo(int)].JML normal_behavior operation contract.0"

BUDGET_MS = 60_000

pytestmark = pytest.mark.skipif(
    not any(each.alive for each in list_instances()),
    reason="no running KeY server; start one on examples/first-proof to run these",
)


@pytest.fixture(scope="module")
def loaded():
    """The example, loaded once. Warm state is the reason a server exists."""
    with KeyClient.discover(EXAMPLE, timeout=120.0) as client:
        task = client.wait_for_task(client.load(EXAMPLE).task_id, timeout=600.0)
        assert task.succeeded, f"the example did not load: {task.error}"
        yield client, task.result["envId"]


@pytest.fixture(scope="module")
def proved(loaded):
    """Each contract run to a verdict, once."""
    client, env_id = loaded
    outcomes = {}
    for contract in (MAX, BROKEN_MAX, SUMMER):
        proof_id = client.start_proof(env_id, contract)
        task = client.wait_for_task(client.run_auto(proof_id, BUDGET_MS).task_id, timeout=600.0)
        assert task.succeeded, f"the search on {contract} failed: {task.error}"
        outcomes[contract] = (proof_id, client.statistics(proof_id))
    return client, outcomes


def test_the_guide_quotes_the_ids_the_server_actually_produces(loaded) -> None:
    client, env_id = loaded
    # Written out in docs/guide.md and in the README so they can be copied. KeY composes them
    # from the class and the signature, so a rename in the example silently invalidates both.
    assert {each.contract_id for each in client.obligations(env_id)} == {MAX, BROKEN_MAX, SUMMER}


def test_max_closes(proved) -> None:
    _, outcomes = proved
    # The one assertion this whole directory exists for. If it fails, every other verdict in the
    # suite is uninterpretable, because a broken setup and an unprovable contract look alike.
    assert outcomes[MAX][1].closed is True
    assert outcomes[MAX][1].open_goals == 0


@pytest.mark.parametrize("contract", [BROKEN_MAX, SUMMER])
def test_the_other_two_do_not_close(proved, contract: str) -> None:
    _, outcomes = proved
    assert outcomes[contract][1].closed is False


def test_nothing_is_waiting_on_a_specification_in_broken_max(proved) -> None:
    client, outcomes = proved
    proof_id, _ = outcomes[BROKEN_MAX]

    per_goal = client.stuck_points(proof_id)

    # The guide prints `no-rule-applies` here and says the code is at fault. That reading is only
    # sound while the list really is empty and the search really did finish looking.
    assert per_goal, "the proof has no open goals, so it must have closed"
    for goal in per_goal:
        assert goal.stuck_points == []
        assert goal.prover_out_of_ideas


def test_summer_names_the_line_that_needs_an_invariant(proved) -> None:
    client, outcomes = proved
    proof_id, _ = outcomes[SUMMER]

    points = [point for goal in client.stuck_points(proof_id) for point in goal.stuck_points]

    # Same verdict as BrokenMax, opposite cause, and the difference is only visible here.
    assert points, "nothing is stuck, so the guide's advice to go and write JML is wrong"
    assert all(point.needs_specification for point in points)

    source = (EXAMPLE / "Summer.java").read_text(encoding="utf-8").splitlines()
    for point in points:
        assert point.source, f"{point.rule_id} reports no file to open"
        assert Path(point.source["file"]).name == "Summer.java"
        # A line number is only useful if it lands on the loop.
        assert "while" in source[point.source["line"] - 1]


def _the_tutorial_s_finished_summer() -> str:
    """The last complete class the walk-through shows, which is the one it says closes."""
    text = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    shown = re.findall(r"```java\n(.*?)```", text, re.S)
    blocks = [each for each in shown if "class Summer" in each]
    assert blocks, "the tutorial no longer shows a complete Summer to copy"
    return blocks[-1]


def test_the_tutorial_closes_what_it_says_it_closes(loaded, tmp_path) -> None:
    client, _ = loaded
    # The walk-through ends on a specification and the words "exit status 0". Proving the block it
    # prints is the only way that claim stays true through a KeY upgrade — and a tutorial whose
    # last step does not work is worse than none, because it is followed rather than skimmed.
    (tmp_path / "Summer.java").write_text(_the_tutorial_s_finished_summer(), encoding="utf-8")

    task = client.wait_for_task(client.load(tmp_path).task_id, timeout=600.0)
    assert task.succeeded, f"the tutorial's Summer did not load: {task.error}"

    proof_id = client.start_proof(task.result["envId"], SUMMER)
    search = client.wait_for_task(client.run_auto(proof_id, BUDGET_MS).task_id, timeout=600.0)
    assert search.succeeded, f"the search failed: {search.error}"
    assert client.statistics(proof_id).closed is True
