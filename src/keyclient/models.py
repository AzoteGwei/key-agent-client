"""Typed views of what the server sends back.

These are plain dataclasses built from the wire objects, and every one keeps the raw dictionary
it came from. New server fields therefore stay reachable through ``raw`` without this package
having to be upgraded in lockstep, which matters while the protocol is young.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "Instance",
    "Environment",
    "ProofObligation",
    "Goal",
    "Sequent",
    "StructuredFormula",
    "Statistics",
    "StuckPoint",
    "GoalDiagnostics",
    "Task",
    "Macro",
    "ApplicableRule",
    "GoalRules",
    "SavedProof",
]


@dataclass(frozen=True)
class Instance:
    """A server this machine has a record of."""

    instance_id: str
    pid: int
    host: str
    port: int
    workspace: str
    api_version: str
    key_version: str
    threads: int
    started_at: str
    alive: bool
    record_path: str
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def stale(self) -> bool:
        """Whether the process that wrote this record is gone.

        A hint rather than a verdict: process ids are reused, so an old record can point at an
        unrelated process. Connect and compare ``instance_id`` when it has to be certain.
        """
        return not self.alive


@dataclass(frozen=True)
class Environment:
    """A loaded project."""

    env_id: str
    path: str = ""
    proof_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ProofObligation:
    """Something that can be proved in an environment."""

    contract_id: str
    kind: str
    target_class: str
    target_member: str
    has_existing_proof: bool
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Goal:
    """An open goal of a proof."""

    proof_id: str
    goal_id: int
    node_id: int
    is_open: bool
    is_linked: bool
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def ref(self) -> dict[str, Any]:
        """The reference to pass back to the server.

        Treat it as opaque. It is handed over as received and never taken apart.
        """
        return dict(self.raw.get("goal") or {"proofId": self.proof_id, "goalId": self.goal_id})


@dataclass(frozen=True)
class StructuredFormula:
    """One formula of a sequent, taken apart into the pieces it is made of.

    A proof obligation in mid-flight is one enormous formula: a symbolic state, then the program
    still to run, then what must hold once it has. Read as one string it is several hundred
    characters with the interesting part at the end. Separated, each piece answers a different
    question.
    """

    side: str
    index: int
    text: str
    claim: str
    state: str | None = None
    program: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def has_program(self) -> bool:
        """Whether this formula still has Java left to execute."""
        return self.program is not None


@dataclass(frozen=True)
class Sequent:
    """The formulas of one goal.

    ``antecedent`` and ``succedent`` are filled whatever format was asked for. ``formulas`` is
    filled only for ``STRUCTURED``.
    """

    antecedent: list[str]
    succedent: list[str]
    format: str
    formulas: list[StructuredFormula] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def __str__(self) -> str:
        lines = [*self.antecedent, "==>", *self.succedent]
        return "\n".join(lines)


@dataclass(frozen=True)
class Statistics:
    """What is known about a proof.

    ``closed`` is the only field that answers "is this verified", and it comes from the server,
    which in turn takes it from KeY's own ``Proof.closed()``. Nothing in this package computes it,
    infers it, or defaults it.
    """

    closed: bool
    open_goals: int
    nodes: int
    branches: int
    total_rule_apps: int
    interactive_steps: int
    symb_ex_apps: int
    smt_solver_apps: int
    loop_inv_apps: int
    operation_contract_apps: int
    dependency_contract_apps: int
    block_loop_contract_apps: int
    auto_mode_time_ms: int
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class StuckPoint:
    """A rule that wants to apply to a goal and cannot."""

    rule_id: str
    rule_name: str
    position_hint: str
    reason: str
    source: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def needs_specification(self) -> bool:
        """Whether this is waiting on a specification somebody has to write."""
        return self.reason == "NEEDS_SPEC"


@dataclass(frozen=True)
class GoalDiagnostics:
    """What stands in the way of one goal.

    An empty ``stuck_points`` is a finding, not a blank: no rule is waiting on anything, so the
    goal is not waiting on a specification you could write.

    Read it with :attr:`last_search_outcome`. Empty after ``EXHAUSTED`` means the prover tried
    everything it knows and got no further, which calls for a script, a solver or an interactive
    step. Empty after a limit means it never finished looking, which calls for more budget. The
    two are the same empty list and opposite problems.
    """

    goal_id: int
    stuck_points: list[StuckPoint]
    truncated: bool
    last_search_outcome: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def prover_out_of_ideas(self) -> bool:
        """Whether the last automatic search ended having nothing left to try.

        ``False`` also when no search has been run, since a search that never happened establishes
        nothing either way.
        """
        return self.last_search_outcome == "EXHAUSTED"


@dataclass(frozen=True)
class SavedProof:
    """Where a proof was written.

    That this exists at all means the file is on disk: a save that did not happen comes back as an
    error, never as a path.
    """

    path: str
    bytes: int
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class ApplicableRule:
    """A rule that applies to a goal here and now, and how to write it down.

    :attr:`script` is the useful field. A rule name alone is often not enough — a third to a half
    of the rules offered on a real goal match in more than one place, and a script naming one
    without saying which is refused — so the line that applies it is given rather than left to be
    reconstructed. It is ``None`` when the rule needs input that cannot be guessed.
    """

    rule_id: str
    kind: str
    occurrences: int = 1
    needs_instantiation: bool = False
    needs_assumption: bool = False
    side: str | None = None
    index: int | None = None
    script: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def applicable_as_is(self) -> bool:
        """Whether :attr:`script` will apply this rule with no further input."""
        return self.script is not None


@dataclass(frozen=True)
class GoalRules:
    """What could still be applied to a goal by hand.

    The complement of :class:`GoalDiagnostics`: those say what wants to apply and cannot, this
    says what could apply and the automatic strategy did not choose.

    Rules carrying a ``script`` can be applied as they stand. The rest are offered because they
    are genuinely applicable and a caller may know what to supply.
    """

    goal_id: int
    rules: list[ApplicableRule]
    truncated: bool
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class Task:
    """A long-running operation.

    ``SUCCEEDED`` means the work finished without throwing. It does **not** mean a proof closed.
    A macro that runs to its end and leaves three goals open is a succeeded task with three open
    goals; ask :attr:`statistics` or ``proof.getStatistics`` about the proof.
    """

    task_id: str
    kind: str
    status: str
    subject: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    progress: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def finished(self) -> bool:
        """Whether the task reached a terminal state, whatever that state is."""
        return self.status in ("SUCCEEDED", "FAILED", "CANCELLED")

    @property
    def succeeded(self) -> bool:
        """Whether the work ran to completion without throwing.

        Says nothing about any proof.
        """
        return self.status == "SUCCEEDED"

    @property
    def statistics(self) -> Statistics | None:
        """The proof statistics a finished search or script carried back, if any."""
        stats = (self.result or {}).get("statistics")
        return _statistics(stats) if stats else None


@dataclass(frozen=True)
class Macro:
    """A proof macro the server can run."""

    macro_id: str
    name: str
    category: str | None = None
    description: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def _statistics(payload: dict[str, Any]) -> Statistics:
    return Statistics(
        closed=bool(payload.get("closed")),
        open_goals=int(payload.get("openGoals", 0)),
        nodes=int(payload.get("nodes", 0)),
        branches=int(payload.get("branches", 0)),
        total_rule_apps=int(payload.get("totalRuleApps", 0)),
        interactive_steps=int(payload.get("interactiveSteps", 0)),
        symb_ex_apps=int(payload.get("symbExApps", 0)),
        smt_solver_apps=int(payload.get("smtSolverApps", 0)),
        loop_inv_apps=int(payload.get("loopInvApps", 0)),
        operation_contract_apps=int(payload.get("operationContractApps", 0)),
        dependency_contract_apps=int(payload.get("dependencyContractApps", 0)),
        block_loop_contract_apps=int(payload.get("blockLoopContractApps", 0)),
        auto_mode_time_ms=int(payload.get("autoModeTimeMs", 0)),
        raw=payload,
    )
