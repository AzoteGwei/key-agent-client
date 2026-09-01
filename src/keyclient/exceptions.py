"""What can go wrong, in a form a program can act on."""

from __future__ import annotations

__all__ = [
    "KeyClientError",
    "KeyServerRpcError",
    "InstanceNotFoundError",
    "TaskTimeoutError",
    "ErrorCode",
]


class ErrorCode:
    """The error codes the server returns.

    Branch on these, never on message text: the messages are for people and will change.
    """

    PARSE_ERROR = -32700
    INVALID_REQUEST = -32600
    METHOD_NOT_FOUND = -32601
    INVALID_PARAMS = -32602
    INTERNAL_ERROR = -32603

    ENV_NOT_FOUND = -32001
    PROOF_NOT_FOUND = -32002
    GOAL_NOT_FOUND = -32003
    LOAD_FAILED = -32004
    SCRIPT_ERROR = -32005
    DIAGNOSTIC_UNAVAILABLE = -32006
    TASK_CONFLICT = -32007
    SOLVER_UNAVAILABLE = -32008
    UNSUPPORTED_FORMAT = -32009
    TASK_NOT_FOUND = -32010


class KeyClientError(Exception):
    """Base class for everything this package raises."""


class KeyServerRpcError(KeyClientError):
    """The server answered with a JSON-RPC error object.

    The whole point of this class is ``code``. Every failure the server can report has a number,
    and a caller that wants to react to one specific failure — a goal that has closed since it
    was listed, a solver that is missing — should compare against :class:`ErrorCode` rather than
    reading the message.
    """

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data or {}

    @property
    def positions(self) -> list[dict]:
        """Source positions the server attached, if any.

        Load failures and script errors carry the file, line and column KeY found the trouble at.
        For anything rewriting a specification or a script, that is the useful part of the error.
        """
        return list(self.data.get("positions") or [])


class InstanceNotFoundError(KeyClientError):
    """No running server could be found to talk to.

    The message carries a command that starts one. That is deliberate: this error is most often
    read by an agent, and an agent that is told what to run can fix its own problem.
    """


class TaskTimeoutError(KeyClientError):
    """A task did not finish within the time the caller allowed.

    The task itself is untouched and still running on the server. Nothing has been cancelled and
    nothing has failed; only the waiting stopped.
    """

    def __init__(self, task_id: str, waited: float) -> None:
        super().__init__(
            f"Task {task_id} was still running after {waited:.0f}s. "
            f"It has not been cancelled; poll task.get or call cancel_task({task_id!r})."
        )
        self.task_id = task_id
        self.waited = waited
