"""The typed client: one method per thing the server can do.

Nothing here decides whether a proof succeeded. Every statement about verification comes back from
the server, which takes it from KeY's own ``Proof.closed()``, and this package passes it along
unchanged. There is no code path that produces a positive verdict on its own — no default, no
fallback, no "the task finished so it must have worked".
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from collections.abc import Iterator
from typing import Any

from .discovery import resolve
from .exceptions import KeyClientError, TaskTimeoutError
from .models import (
    Environment,
    Goal,
    GoalDiagnostics,
    Instance,
    Macro,
    ProofObligation,
    Sequent,
    Statistics,
    StuckPoint,
    Task,
    _statistics,
)
from .rpc import RpcTransport

__all__ = ["KeyClient"]


class KeyClient:
    """A conversation with one running KeY server.

    Usable as a context manager. There is nothing to shut down on the server — instances outlive
    clients on purpose, which is the point of the whole arrangement — so leaving the block only
    stops this object being used.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int | None = None,
        *,
        timeout: float = 30.0,
        instance: Instance | None = None,
    ) -> None:
        if port is None and instance is None:
            raise ValueError("Give a port or an instance; use KeyClient.discover() to find one")
        if instance is not None:
            host, port = instance.host, instance.port
        assert port is not None
        self.instance = instance
        self.rpc = RpcTransport(host, port, timeout=timeout)

    @classmethod
    def discover(
        cls,
        workspace: str | os.PathLike[str] | None = None,
        instance_id: str | None = None,
        *,
        timeout: float = 30.0,
    ) -> KeyClient:
        """Finds a running server and connects to it.

        :raises InstanceNotFoundError: when there is none, with a command that starts one
        """
        return cls(instance=resolve(workspace, instance_id), timeout=timeout)

    def __enter__(self) -> KeyClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    # -- server ---------------------------------------------------------------------------

    def version(self) -> dict[str, Any]:
        """Who this is and what it speaks."""
        return self.rpc.call("server.version")

    def health(self) -> bool:
        """Whether the server answers at all."""
        return bool(self.rpc.call("server.health").get("ok"))

    # -- environments ---------------------------------------------------------------------

    def load(self, path: str | os.PathLike[str], **options: Any) -> Task:
        """Starts loading a project, returning at once.

        Loading a real project takes far longer than a request should, so this hands back a task.
        Wait for it with :meth:`wait_for_task`.
        """
        params: dict[str, Any] = {"path": str(path)}
        params.update({key: value for key, value in options.items() if value is not None})
        return _task(self.rpc.call("environment.load", params))

    def environments(self) -> list[Environment]:
        """Every project this server has loaded."""
        return [
            Environment(
                env_id=each["envId"],
                path=each.get("path", ""),
                proof_count=int(each.get("proofCount", 0)),
                raw=each,
            )
            for each in self.rpc.call("environment.list")
        ]

    def close_environment(self, env_id: str) -> bool:
        """Releases a project and every proof belonging to it."""
        return bool(self.rpc.call("environment.close", {"env": {"envId": env_id}}).get("ok"))

    def obligations(
        self,
        env_id: str,
        target_class: str | None = None,
        *,
        include_library_classes: bool = False,
    ) -> list[ProofObligation]:
        """What can be proved in a project.

        The JDK stubs KeY loads alongside a project are left out unless asked for; there are
        several hundred of them and they bury the project's own contracts.
        """
        params: dict[str, Any] = {"env": {"envId": env_id}}
        if target_class is not None:
            params["targetClass"] = target_class
        if include_library_classes:
            params["includeLibraryClasses"] = True
        return [
            ProofObligation(
                contract_id=each["contractId"],
                kind=each["kind"],
                target_class=each["targetClass"],
                target_member=each["targetMember"],
                has_existing_proof=bool(each.get("hasExistingProof")),
                raw=each,
            )
            for each in self.rpc.call("environment.listProofObligations", params)
        ]

    # -- proofs ---------------------------------------------------------------------------

    def start_proof(self, env_id: str, contract_id: str) -> str:
        """Creates a proof for one contract and returns its identifier."""
        return self.rpc.call("proof.start", {"env": {"envId": env_id}, "contractId": contract_id})[
            "proofId"
        ]

    def run_auto(self, proof_id: str, timeout_ms: int | None = None) -> Task:
        """Starts the automatic search, returning at once.

        ``timeout_ms`` is a wall-clock budget. When it runs out the search is interrupted and
        whatever it reached is reported; that is not a failure and not a success.
        """
        params: dict[str, Any] = {"proof": {"proofId": proof_id}}
        if timeout_ms is not None:
            params["timeoutMs"] = timeout_ms
        return _task(self.rpc.call("proof.runAuto", params))

    def statistics(self, proof_id: str) -> Statistics:
        """What is known about a proof right now.

        ``closed`` is the only answer to "is this verified", and it is the server's answer.
        """
        return _statistics(self.rpc.call("proof.getStatistics", {"proof": {"proofId": proof_id}}))

    def close_proof(self, proof_id: str) -> bool:
        """Releases a proof."""
        return bool(self.rpc.call("proof.close", {"proof": {"proofId": proof_id}}).get("ok"))

    # -- goals ----------------------------------------------------------------------------

    def goals(self, proof_id: str, *, include_closed: bool = False) -> list[Goal]:
        """The goals of a proof, open ones by default."""
        params: dict[str, Any] = {"proof": {"proofId": proof_id}}
        if include_closed:
            params["includeClosed"] = True
        return [
            Goal(
                proof_id=each["goal"]["proofId"],
                goal_id=int(each["goalId"]),
                node_id=int(each["nodeId"]),
                is_open=bool(each["isOpen"]),
                is_linked=bool(each["isLinked"]),
                raw=each,
            )
            for each in self.rpc.call("goal.list", params)
        ]

    def sequent(self, proof_id: str, goal_id: int, fmt: str = "TEXT") -> Sequent:
        """The formulas of one goal.

        Only ``TEXT`` is implemented. Asking for another format is refused rather than answered
        with text under the wrong label.
        """
        payload = self.rpc.call(
            "goal.getSequent",
            {"goal": {"proofId": proof_id, "goalId": goal_id}, "format": fmt},
        )
        return Sequent(
            antecedent=list(payload.get("antecedent", [])),
            succedent=list(payload.get("succedent", [])),
            format=payload.get("format", fmt),
            raw=payload,
        )

    def macros(self, proof_id: str) -> list[Macro]:
        """The macros this server can run."""
        return [
            Macro(
                macro_id=each["macroId"],
                name=each.get("name", ""),
                category=each.get("category"),
                description=each.get("description"),
                raw=each,
            )
            for each in self.rpc.call("goal.listAvailableMacros", {"proof": {"proofId": proof_id}})
        ]

    def apply_macro(self, proof_id: str, macro_id: str, goal_id: int | None = None) -> Task:
        """Runs a macro, returning at once."""
        params: dict[str, Any] = {"proof": {"proofId": proof_id}, "macroId": macro_id}
        if goal_id is not None:
            params["goal"] = {"proofId": proof_id, "goalId": goal_id}
        return _task(self.rpc.call("goal.applyMacro", params))

    def apply_script(self, proof_id: str, goal_id: int, script: str) -> Task:
        """Runs a proof script from one goal, returning at once.

        Scripts are preferred over macros: they are reproducible, they can be saved next to the
        code they prove, and their meaning is KeY's rather than this client's.
        """
        return _task(
            self.rpc.call(
                "goal.applyScript",
                {"goal": {"proofId": proof_id, "goalId": goal_id}, "script": script},
            )
        )

    # -- diagnostics ----------------------------------------------------------------------

    def explain_goal(
        self, proof_id: str, goal_id: int, max_depth: int | None = None
    ) -> GoalDiagnostics:
        """Why one goal is not closing."""
        params: dict[str, Any] = {"goal": {"proofId": proof_id, "goalId": goal_id}}
        if max_depth is not None:
            params["maxDepth"] = max_depth
        return _diagnostics(self.rpc.call("diagnostics.explainGoal", params))

    def stuck_points(self, proof_id: str, max_depth: int | None = None) -> list[GoalDiagnostics]:
        """Why each open goal of a proof is not closing.

        An empty list of stuck points for a goal means no rule is waiting on anything: the goal is
        not under-specified, it is most likely simply not provable.
        """
        params: dict[str, Any] = {"proof": {"proofId": proof_id}}
        if max_depth is not None:
            params["maxDepth"] = max_depth
        found = self.rpc.call("diagnostics.listStuckPoints", params)
        return [_diagnostics(each) for each in found]

    # -- tasks ----------------------------------------------------------------------------

    def task(self, task_id: str) -> Task:
        """One task, exactly as the server has it.

        The bare call is kept alongside :meth:`wait_for_task` on purpose: a caller that wants to
        do something else between polls should not have to give up the typed method to do it.
        """
        return _task(self.rpc.call("task.get", {"taskId": task_id}))

    def tasks(self) -> list[Task]:
        """Every task this server knows about."""
        return [_task(each) for each in self.rpc.call("task.list")]

    def cancel_task(self, task_id: str) -> bool:
        """Asks a task to stop.

        The answer says whether the request was passed on, not that the task has stopped. KeY
        notices between rule applications; poll until the status reaches ``CANCELLED``.
        """
        return bool(self.rpc.call("task.cancel", {"taskId": task_id}).get("ok"))

    def wait_for_task(
        self, task_id: str, *, poll_interval: float = 0.5, timeout: float | None = 3600.0
    ) -> Task:
        """Polls a task until it reaches a terminal state.

        :raises TaskTimeoutError: when the budget runs out. The task keeps running; nothing here
            cancels it, because a caller that wanted it stopped would have said so.
        """
        started = time.monotonic()
        while True:
            current = self.task(task_id)
            if current.finished:
                return current
            waited = time.monotonic() - started
            if timeout is not None and waited >= timeout:
                raise TaskTimeoutError(task_id, waited)
            time.sleep(poll_interval)

    def events(self, *, timeout: float | None = None) -> Iterator[dict[str, Any]]:
        """Yields task notifications as the server pushes them.

        An alternative to polling for callers that would rather be told. The iterator ends when
        the stream does; a broken connection raises rather than reconnecting, for the same reason
        nothing else here retries.
        """
        request = urllib.request.Request(
            self.rpc.url, headers={"Accept": "text/event-stream"}, method="GET"
        )
        try:
            stream = urllib.request.urlopen(request, timeout=timeout)
        except OSError as error:
            raise KeyClientError(
                f"Could not open the event stream at {self.rpc.url}: {error}"
            ) from error
        with stream:
            for line in stream:
                text = line.decode("utf-8").rstrip("\n")
                if text.startswith("data: "):
                    yield json.loads(text[len("data: ") :])


def _task(payload: dict[str, Any]) -> Task:
    return Task(
        task_id=payload["taskId"],
        kind=payload.get("kind", ""),
        status=payload.get("status", ""),
        subject=payload.get("subject"),
        result=payload.get("result"),
        progress=payload.get("progress"),
        error=payload.get("error"),
        raw=payload,
    )


def _diagnostics(payload: dict[str, Any]) -> GoalDiagnostics:
    return GoalDiagnostics(
        goal_id=int(payload["goalId"]),
        stuck_points=[
            StuckPoint(
                rule_id=each["ruleId"],
                rule_name=each.get("ruleName", ""),
                position_hint=each.get("positionHint", ""),
                reason=each.get("reason", ""),
                source=each.get("source"),
                raw=each,
            )
            for each in payload.get("stuckPoints", [])
        ],
        truncated=bool(payload.get("truncated")),
        raw=payload,
    )
