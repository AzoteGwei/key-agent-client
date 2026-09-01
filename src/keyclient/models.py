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
    "Statistics",
    "StuckPoint",
    "GoalDiagnostics",
    "Task",
    "Macro",
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
class Sequent:
    """The formulas of one goal."""

    antecedent: list[str]
    succedent: list[str]
    format: str
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
    goal is not under-specified and is most likely simply not provable.
    """

    goal_id: int
    stuck_points: list[StuckPoint]
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
