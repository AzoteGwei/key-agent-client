"""What the MCP tools put in front of a model.

These tests are mostly about words. The tools are read by something that will act on them, and the
difference between "the search finished" and "the contract holds" is a difference the reader
cannot recover if the text blurs it. So the assertions are on what the text says, and above all
on what it must never say.
"""

from __future__ import annotations

import asyncio

import pytest
from conftest import FakeServer

from keyclient.mcp import Settings, build_server

pytest.importorskip("mcp", reason="the MCP server needs the optional mcp extra")

#: Words a model would read as a verdict. None may appear about a proof that did not close.
SUCCESS_WORDS = ("proved", "verified", "success", "succeeded", "holds", "correct")


def server(fake: FakeServer, monkeypatch, tmp_path):
    """Builds a server pointed at the stand-in, bypassing instance discovery."""
    from keyclient import mcp as module
    from keyclient.client import KeyClient

    monkeypatch.setattr(module, "_connect", lambda settings: KeyClient("127.0.0.1", fake.port))
    return build_server(Settings(workspace=str(tmp_path)))


def call(built, name: str, **arguments) -> str:
    result = asyncio.run(built.call_tool(name, arguments))
    text = result[0] if isinstance(result, tuple) else result
    return "\n".join(getattr(block, "text", str(block)) for block in text)


def _proof(fake: FakeServer, *, closed: bool, outcome: str = "EXHAUSTED") -> None:
    fake.answer("proof.start", {"proofId": "prf-1"})
    fake.answer("proof.runAuto", {"taskId": "task-1", "kind": "AUTO", "status": "PENDING"})
    fake.answer(
        "task.get",
        {
            "taskId": "task-1",
            "kind": "AUTO",
            "status": "SUCCEEDED",
            "result": {"outcome": outcome, "statistics": {"closed": closed}},
        },
    )
    fake.answer(
        "proof.getStatistics",
        {"closed": closed, "openGoals": 0 if closed else 2, "nodes": 20, "totalRuleApps": 40},
    )


def test_an_unproved_contract_is_never_described_as_proved(fake, monkeypatch, tmp_path) -> None:
    _proof(fake, closed=False)
    fake.answer("goal.list", [])
    built = server(fake, monkeypatch, tmp_path)

    answer = call(built, "key_prove", env="env-1", contract_id="C").lower()

    # The single assertion this whole surface exists to satisfy. A model reading any of these
    # words about an open proof would report unverified code as verified.
    for word in SUCCESS_WORDS:
        assert word not in answer, f"{word!r} appears about a proof that did not close"
    assert "closed: false" in answer
    assert "did not close" in answer


def test_a_prover_out_of_ideas_is_told_apart_from_one_out_of_budget(
    fake, monkeypatch, tmp_path
) -> None:
    _proof(fake, closed=False, outcome="EXHAUSTED")
    fake.answer("goal.list", [])
    built = server(fake, monkeypatch, tmp_path)
    exhausted = call(built, "key_prove", env="env-1", contract_id="C")

    _proof(fake, closed=False, outcome="BUDGET_ELAPSED")
    cut_short = call(built, "key_prove", env="env-1", contract_id="C")

    _proof(fake, closed=False, outcome="MAX_RULES")
    capped = call(built, "key_prove", env="env-1", contract_id="C")

    # Same open proof, three different next steps. Collapsing any two would send an agent off
    # raising a budget that is not the problem, or rewriting a specification that is fine.
    assert "more time will not help" in exhausted
    assert "Raise budget_ms" in cut_short
    assert "says nothing about whether the contract holds" in cut_short
    # MAX_RULES is a cap on rule applications, not a clock. An agent told to raise the budget
    # raises budget_ms, hits the cap again, and loops.
    assert "says nothing about whether the contract holds" in capped
    assert "larger budget_ms will not change it" in capped
    assert "MaximumNumberOfAutomaticApplications" in capped


def test_an_open_proof_says_which_goals_to_act_on(fake, monkeypatch, tmp_path) -> None:
    _proof(fake, closed=False)
    fake.answer(
        "goal.list",
        [
            {
                "goal": {"proofId": "prf-1", "goalId": 42},
                "goalId": 42,
                "nodeId": 42,
                "isOpen": True,
                "isLinked": False,
            }
        ],
    )
    built = server(fake, monkeypatch, tmp_path)

    answer = call(built, "key_prove", env="env-1", contract_id="C")

    # Every next step addresses a goal, and node numbers move as a proof grows. Making the caller
    # fetch them separately is one more round trip and one more chance to use a stale one.
    assert "openGoalIds: [42]" in answer


def test_a_closed_proof_says_so_plainly(fake, monkeypatch, tmp_path) -> None:
    _proof(fake, closed=True)
    built = server(fake, monkeypatch, tmp_path)

    answer = call(built, "key_prove", env="env-1", contract_id="C")

    assert "closed: true" in answer
    assert "The contract holds." in answer


def test_inspect_gives_a_different_conclusion_for_each_reason(fake, monkeypatch, tmp_path) -> None:
    fake.answer("proof.getStatistics", {"closed": False, "openGoals": 3})
    fake.answer(
        "goal.list",
        [
            {
                "goal": {"proofId": "prf-1", "goalId": n},
                "goalId": n,
                "nodeId": n,
                "isOpen": True,
                "isLinked": False,
            }
            for n in (1, 2, 3)
        ],
    )
    fake.answer(
        "goal.getSequent",
        {
            "antecedent": ["n >= 0"],
            "succedent": ["{i:=1} \\<{ while (i <= n) ; }\\> (total >= 0)"],
            "format": "STRUCTURED",
            "formulas": [
                {"side": "ANTECEDENT", "index": 0, "text": "n >= 0", "claim": "n >= 0"},
                {
                    "side": "SUCCEDENT",
                    "index": 0,
                    "text": "{i:=1} \\<{ while (i <= n) ; }\\> (total >= 0)",
                    "state": "{i:=1}",
                    "program": "{ while (i <= n) ; }",
                    "claim": "… \\<…\\> (total >= 0)",
                },
            ],
        },
    )
    fake.answer(
        "diagnostics.listStuckPoints",
        [
            {
                "goalId": 1,
                "truncated": False,
                "lastSearchOutcome": "EXHAUSTED",
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
            {"goalId": 2, "truncated": False, "lastSearchOutcome": "EXHAUSTED", "stuckPoints": []},
            {
                "goalId": 3,
                "truncated": False,
                "lastSearchOutcome": "BUDGET_ELAPSED",
                "stuckPoints": [],
            },
        ],
    )
    # Goal 2 is spent with nothing stuck, so inspect asks what could still be applied there.
    fake.answer("diagnostics.listApplicableRules", {"goalId": 2, "truncated": False, "rules": []})
    built = server(fake, monkeypatch, tmp_path)

    answer = call(built, "key_inspect", proof_id="prf-1")

    assert "A specification is missing" in answer
    assert "Summer.java:26" in answer
    assert "run out of things to try" in answer
    assert "stopped before it finished looking" in answer

    # And the goal is laid out as its pieces rather than as one formula to be parsed. This is
    # the tool whose whole job is to be read, and a several-hundred-character blob is not read.
    assert "symbolic state:" in answer
    assert "still to execute:" in answer
    assert "while (i <= n)" in answer
    assert "must hold:" in answer
    assert "assumed:" in answer


def test_inspect_offers_rules_only_where_they_are_the_thing_left(
    fake, monkeypatch, tmp_path
) -> None:
    fake.answer("proof.getStatistics", {"closed": False, "openGoals": 1})
    fake.answer(
        "goal.list",
        [
            {
                "goal": {"proofId": "prf-1", "goalId": 7},
                "goalId": 7,
                "nodeId": 7,
                "isOpen": True,
                "isLinked": False,
            }
        ],
    )
    fake.answer(
        "goal.getSequent",
        {
            "antecedent": [],
            "succedent": ["a >= 0"],
            "format": "STRUCTURED",
            "formulas": [{"side": "SUCCEDENT", "index": 0, "text": "a >= 0", "claim": "a >= 0"}],
        },
    )
    fake.answer(
        "diagnostics.listStuckPoints",
        [{"goalId": 7, "truncated": False, "lastSearchOutcome": "EXHAUSTED", "stuckPoints": []}],
    )
    fake.answer(
        "diagnostics.listApplicableRules",
        {
            "goalId": 7,
            "truncated": False,
            "rules": [
                {
                    "ruleId": "geq_to_leq",
                    "kind": "FIND",
                    "occurrences": 1,
                    "needsInstantiation": False,
                    "needsAssumption": False,
                    "script": 'rule "geq_to_leq";',
                },
                {
                    "ruleId": "hide_left",
                    "kind": "FIND",
                    "occurrences": 3,
                    "needsInstantiation": False,
                    "needsAssumption": False,
                    "script": 'rule "hide_left" occ=0;',
                },
                {
                    "ruleId": "cut",
                    "kind": "NO_FIND",
                    "occurrences": 1,
                    "needsInstantiation": True,
                    "needsAssumption": False,
                },
            ],
        },
    )
    built = server(fake, monkeypatch, tmp_path)

    answer = call(built, "key_inspect", proof_id="prf-1")

    # Offered only where they are the answer: the search is spent and nothing is waiting on a
    # specification, so what a person could still apply is all that is left.
    #
    # And offered as lines, not names. A name still has to be turned into something that applies,
    # and that is the step that goes wrong — hide_left matches three times, so a script naming it
    # alone is refused and the occurrence has to be in there.
    assert 'rule "geq_to_leq";' in answer
    assert 'rule "hide_left" occ=0;' in answer
    assert "counting from zero" in answer
    # The one that cannot be applied as it stands is named without a line, rather than listed
    # alongside as though it were interchangeable.
    assert "supply an instantiation" in answer
    assert "cut" in answer


def test_a_save_that_failed_is_not_reported_as_a_file(fake, monkeypatch, tmp_path) -> None:
    fake.fail("proof.save", -32011, "KeY could not write /proc/x")
    built = server(fake, monkeypatch, tmp_path)

    answer = call(built, "key_save", proof_id="prf-1")

    assert "NOT written" in answer
    assert "-32011" in answer


def test_every_tool_explains_itself_and_the_risky_ones_carry_the_warning(
    fake, monkeypatch, tmp_path
) -> None:
    built = server(fake, monkeypatch, tmp_path)

    tools = {tool.name: tool for tool in asyncio.run(built.list_tools())}

    assert set(tools) == {
        "key_load",
        "key_prove",
        "key_inspect",
        "key_script",
        "key_save",
        "key_server",
    }
    for name, tool in tools.items():
        assert tool.description, f"{name} has no description"

    # The two tools that run a prover are the two where "it finished" is most likely to be read
    # as "it worked", so they say otherwise in the description a model sees before calling.
    for name in ("key_prove", "key_script"):
        assert "not a proved contract" in tools[name].description
        assert "closed" in tools[name].description
