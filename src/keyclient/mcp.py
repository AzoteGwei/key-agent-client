"""An MCP server exposing the KeY prover to an agent.

This process holds no prover. It connects to a `keyext.server` that is already running and
forwards, which is the point: a JVM with a loaded project takes tens of seconds to warm up and
must outlive the conversation that uses it. An MCP server that owned one would pay that cost
again for every new chat, and the warm state this whole thing exists for would never be warm.

It also means nothing here can decide that a proof succeeded. There is no KeY in this process to
ask; every verdict is the server's, which takes it from KeY's own ``Proof.closed()``.

**The tools do not expose tasks.** The RPC protocol answers a long operation with a handle and
lets the caller poll, which is right for a protocol and wrong for a tool: it puts a status called
``SUCCEEDED`` in front of a model, meaning "the work finished", next to a proof that did not
close. Each tool here waits for its own work and reports the proof. There is no SUCCEEDED to
misread.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any

from .client import KeyClient
from .discovery import START_HINT, resolve
from .exceptions import InstanceNotFoundError, KeyClientError, KeyServerRpcError
from .models import GoalDiagnostics, Sequent, Statistics, Task

__all__ = ["build_server", "main"]

#: Default wall-clock budget for a proof search, in milliseconds.
#:
#: Deliberately short. A tool call that blocks for an hour is worse for an agent than one that
#: comes back and says it needs longer, because the second can be acted on.
DEFAULT_BUDGET_MS = 60_000

NOT_A_SUCCESS = (
    "A finished search is not a proved contract. Read `closed`: it is KeY's own answer and the "
    "only one that means anything here."
)


@dataclass
class Settings:
    """How this server was started."""

    workspace: str | None = None
    instance: str | None = None
    timeout: float = 900.0


def _connect(settings: Settings) -> KeyClient:
    """Finds the running server, or explains how to start one."""
    try:
        return KeyClient(
            instance=resolve(settings.workspace, settings.instance), timeout=settings.timeout
        )
    except InstanceNotFoundError as error:
        raise KeyClientError(str(error)) from error


def _verdict(statistics: Statistics, outcome: str | None = None) -> str:
    """States what is true of a proof, in the words the reader should end up with.

    Written out rather than left for the model to infer from a boolean, because inference is
    exactly where "the tool call worked" turns into "the code is verified".
    """
    if statistics.closed:
        return "closed: true — KeY closed this proof. The contract holds."
    lines = [
        f"closed: false — the proof did NOT close. {statistics.open_goals} goal(s) remain open.",
    ]
    if outcome == "EXHAUSTED":
        lines.append(
            "The prover ran out of things to try, so more time will not help. Use key_inspect "
            "to see what is open, then a proof script, a solver, or a missing specification."
        )
    elif outcome in ("MAX_RULES", "BUDGET_ELAPSED", "STRATEGY_TIMEOUT"):
        lines.append(
            "The search was stopped before it finished looking, so this says nothing about "
            "whether the contract holds. Raise the budget and try again."
        )
    return "\n".join(lines)


def _statistics_lines(statistics: Statistics) -> str:
    return (
        f"openGoals: {statistics.open_goals}\n"
        f"nodes: {statistics.nodes}\n"
        f"ruleApplications: {statistics.total_rule_apps}\n"
        f"smtSolverApplications: {statistics.smt_solver_apps}"
    )


def _render_sequent(sequent: Sequent) -> str:
    """Lays a sequent out as the pieces it is made of.

    A goal in mid-execution is one formula of several hundred characters whose interesting part is
    at the end. Printed whole it has to be parsed before it can be read; laid out as what is
    assumed, what the state is, what is left to run and what must hold, each line answers a
    question on its own.
    """
    if not sequent.formulas:
        return str(sequent)

    assumed = [each.text for each in sequent.formulas if each.side == "ANTECEDENT"]
    lines = []
    if assumed:
        lines.append("assumed:\n  " + "\n  ".join(assumed))
    for formula in sequent.formulas:
        if formula.side != "SUCCEDENT":
            continue
        if formula.state:
            lines.append(f"symbolic state:\n  {formula.state}")
        if formula.program:
            lines.append(f"still to execute:\n  {formula.program}")
        lines.append(f"must hold:\n  {formula.claim}")
    return "\n\n".join(lines)


def _goal_finding(goal: GoalDiagnostics, sequent: str) -> str:
    """Turns one goal's diagnostics into the conclusion an agent should act on."""
    if goal.stuck_points:
        header = "A specification is missing. These rules apply here and cannot be instantiated:"
        points = []
        for point in goal.stuck_points:
            where = point.source or {}
            place = (
                f"{where.get('file', '')}:{where.get('line', 0)}" if where else point.position_hint
            )
            points.append(f"  - {point.rule_name} ({point.reason}) at {place}")
        body = "\n".join(points)
    elif goal.prover_out_of_ideas:
        header = (
            "Nothing is waiting on a specification, and the prover has run out of things to "
            "try. This goal needs a proof script, a solver, or is not provable as stated."
        )
        body = ""
    else:
        header = (
            "Nothing is waiting on a specification, but the last search was stopped before it "
            "finished looking. Run key_prove again with a larger budget before concluding "
            "anything about this goal."
        )
        body = ""
    return f"goal {goal.goal_id}: {header}\n{body}\n\nsequent:\n{sequent}".strip()


def build_server(settings: Settings) -> Any:
    """Builds the MCP server with its tools.

    Separated from :func:`main` so the tools can be exercised without a transport.
    """
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(
        name="key-agent",
        version="0.1.0",
        instructions=(
            "Prove JML-specified Java with the KeY theorem prover.\n\n"
            "The workflow is: key_load a project, key_prove a contract from it, and when a proof "
            "does not close, key_inspect it to find out why and key_script to push it along. "
            "key_save writes a proof to disk so the result can be reviewed and committed.\n\n"
            f"{NOT_A_SUCCESS} A tool returning normally means the tool ran, nothing more."
        ),
    )

    @server.tool(
        description=(
            "Load a Java project, a .key problem file or a saved .proof, and list what can be "
            "proved in it. Point this at a directory of Java sources, or at the project's own "
            ".key file when it declares a class path or includes — a real project usually does, "
            "and loading it by its source directory then fails with an unresolved symbol."
        )
    )
    def key_load(path: str) -> str:
        with _connect(settings) as key:
            task = key.wait_for_task(key.load(path).task_id, timeout=settings.timeout)
            if not task.succeeded:
                return _failed(task, f"Loading {path} failed.")
            env = (task.result or {})["envId"]
            obligations = key.obligations(env)

        if not obligations:
            return (
                f"environment: {env}\n\nNo proof obligations. The sources carry no JML "
                "specification, or KeY did not find the class you expected."
            )
        listed = "\n".join(
            f"  {each.target_class}.{each.target_member}  [{each.kind}]  {each.contract_id}"
            for each in obligations
        )
        return f"environment: {env}\n{len(obligations)} obligation(s):\n{listed}"

    @server.tool(
        description=(
            "Start a proof for one contract and run KeY's automatic search on it. "
            f"{NOT_A_SUCCESS} When the proof does not close, the answer says whether the prover "
            "ran out of ideas or merely ran out of budget, which call for different next steps."
        )
    )
    def key_prove(env: str, contract_id: str, budget_ms: int = DEFAULT_BUDGET_MS) -> str:
        with _connect(settings) as key:
            proof = key.start_proof(env, contract_id)
            task = key.wait_for_task(
                key.run_auto(proof, budget_ms).task_id, timeout=settings.timeout
            )
            if not task.succeeded:
                return _failed(task, f"The search on {proof} failed.")
            outcome = (task.result or {}).get("outcome")
            # Asked of the proof, not concluded from the search having returned.
            statistics = key.statistics(proof)
            # Carried back with the verdict because every next step needs one: key_inspect and
            # key_script both address a goal, and node numbers move as a proof grows, so an id
            # fetched a moment earlier is not necessarily one that still exists.
            open_goals = [] if statistics.closed else [each.goal_id for each in key.goals(proof)]

        answer = (
            f"proof: {proof}\n"
            f"{_verdict(statistics, outcome)}\n\n"
            f"searchEnded: {outcome}\n{_statistics_lines(statistics)}"
        )
        return answer if statistics.closed else f"{answer}\nopenGoalIds: {open_goals}"

    @server.tool(
        description=(
            "Report why the open goals of a proof are not closing. Each goal is laid out as "
            "what is assumed, the symbolic state, the program still to execute and what must "
            "hold once it has, together with whether the goal is waiting on a specification you "
            "could write, on a proof step the automatic search cannot find, or merely on more "
            "search budget."
        )
    )
    def key_inspect(proof_id: str, max_goals: int = 5) -> str:
        with _connect(settings) as key:
            statistics = key.statistics(proof_id)
            if statistics.closed:
                return (
                    f"proof: {proof_id}\nclosed: true — nothing is open, so there is nothing "
                    "to inspect."
                )
            goals = key.goals(proof_id)
            diagnostics = {each.goal_id: each for each in key.stuck_points(proof_id)}
            findings = []
            for goal in goals[:max_goals]:
                # Structured, because this is the tool whose whole job is to be readable.
                sequent = _render_sequent(key.sequent(proof_id, goal.goal_id, "STRUCTURED"))
                finding = diagnostics.get(goal.goal_id)
                if finding is None:
                    findings.append(f"goal {goal.goal_id}:\n{sequent}")
                else:
                    findings.append(_goal_finding(finding, sequent))

        more = (
            f"\n\n({len(goals) - max_goals} further open goal(s) not shown.)"
            if len(goals) > max_goals
            else ""
        )
        return (
            f"proof: {proof_id}\nclosed: false — {statistics.open_goals} goal(s) open.\n\n"
            + "\n\n---\n\n".join(findings)
            + more
        )

    @server.tool(
        description=(
            "Apply a KeY proof script to one goal and report what the proof looks like "
            "afterwards. Scripts are the preferred way to push a proof along: they are "
            "reproducible and can be saved next to the code. Useful commands are "
            '`macro "symbex";` to run symbolic execution and `smt;` to hand a goal to a solver. '
            f"{NOT_A_SUCCESS}"
        )
    )
    def key_script(proof_id: str, goal_id: int, script: str) -> str:
        with _connect(settings) as key:
            try:
                task = key.wait_for_task(
                    key.apply_script(proof_id, goal_id, script).task_id, timeout=settings.timeout
                )
            except KeyServerRpcError as error:
                return _rpc_error(error, "The script was refused.")
            if not task.succeeded:
                return _failed(task, "The script failed.")
            statistics = key.statistics(proof_id)
            open_goals = [each.goal_id for each in key.goals(proof_id)]

        return (
            f"proof: {proof_id}\n{_verdict(statistics)}\n\n"
            f"openGoalIds: {open_goals}\n{_statistics_lines(statistics)}"
        )

    @server.tool(
        description=(
            "Write a proof to disk in KeY's own format so it can be reviewed, re-checked by KeY "
            "and committed. Save a proof once it closes; an unclosed proof can be saved too and "
            "comes back exactly as unclosed."
        )
    )
    def key_save(proof_id: str, path: str | None = None, as_bundle: bool = False) -> str:
        with _connect(settings) as key:
            try:
                saved = key.save_proof(proof_id, path, as_bundle=as_bundle)
            except KeyServerRpcError as error:
                return _rpc_error(error, "The proof was NOT written.")
            statistics = key.statistics(proof_id)
        return f"written: {saved.path} ({saved.bytes} bytes)\n{_verdict(statistics)}"

    @server.tool(description="Report which KeY server this is connected to.")
    def key_server() -> str:
        with _connect(settings) as key:
            version = key.version()
            instance = key.instance
        workspace = instance.workspace if instance else "unknown"
        return (
            f"instance: {version['instanceId']}\n"
            f"endpoint: {key.rpc.url}\n"
            f"workspace: {workspace}\n"
            f"apiVersion: {version['apiVersion']}\n"
            f"keyVersion: {version['keyVersion']}"
        )

    return server


def _failed(task: Task, headline: str) -> str:
    error = task.error or {}
    lines = [headline, f"status: {task.status}"]
    if error.get("detail"):
        lines.append(str(error["detail"]))
    for position in error.get("positions") or []:
        lines.append(
            f"  at {position.get('file', '?')}:{position.get('line', 0)}"
            f":{position.get('column', 0)}: {position.get('message', '')}"
        )
    return "\n".join(lines)


def _rpc_error(error: KeyServerRpcError, headline: str) -> str:
    lines = [headline, f"{error.message} (code {error.code})"]
    for position in error.positions:
        lines.append(
            f"  at {position.get('file', '?')}:{position.get('line', 0)}"
            f":{position.get('column', 0)}: {position.get('message', '')}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Runs the MCP server on stdio."""
    parser = argparse.ArgumentParser(
        prog="key-agent-mcp",
        description=(
            "MCP server for the KeY theorem prover. Connects to a running keyext.server; it does "
            "not start one. Third-party tool, not part of the KeY project."
        ),
    )
    parser.add_argument(
        "--workspace",
        default=os.getcwd(),
        help="prefer the server anchored to this directory (default: cwd)",
    )
    parser.add_argument("--instance", default=None, help="connect to this instance id")
    parser.add_argument(
        "--timeout",
        type=float,
        default=900.0,
        help="seconds to wait for one operation (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    settings = Settings(workspace=args.workspace, instance=args.instance, timeout=args.timeout)
    try:
        resolve(settings.workspace, settings.instance)
    except InstanceNotFoundError:
        # Reported and then started anyway: the tools each resolve for themselves, so a server
        # started after this one is still found. Stopping here would make the order of startup
        # matter, which is not something a person configuring an MCP client should have to think
        # about.
        print(
            "No KeY server found yet; tools will look again on each call.\n"
            f"Start one with:\n    {START_HINT.format(workspace=settings.workspace)}",
            file=sys.stderr,
        )

    build_server(settings).run(transport="stdio")
    return 0


if __name__ == "__main__":
    sys.exit(main())
