"""A Python client for the headless KeY theorem prover server.

This package talks to a running ``keyext.server`` over JSON-RPC and does nothing else. It contains
no Java, ships no jar, and never starts a JVM: the server is somebody else's process with its own
lifetime, which is the entire reason it is worth talking to rather than re-running.

It also never decides that a proof succeeded. Every statement about verification is the server's,
taken from KeY's own ``Proof.closed()`` and passed through unchanged.

This is a third-party tool. It is not part of the KeY project.
"""

from __future__ import annotations

from .client import KeyClient
from .discovery import list_instances, resolve
from .exceptions import (
    ErrorCode,
    InstanceNotFoundError,
    KeyClientError,
    KeyServerRpcError,
    TaskTimeoutError,
)
from .models import (
    ApplicableRule,
    Environment,
    Goal,
    GoalDiagnostics,
    GoalRules,
    Instance,
    Macro,
    ProofObligation,
    SavedProof,
    Sequent,
    Statistics,
    StructuredFormula,
    StuckPoint,
    Task,
)

__version__ = "0.1.0"

__all__ = [
    "KeyClient",
    "list_instances",
    "resolve",
    "ErrorCode",
    "InstanceNotFoundError",
    "KeyClientError",
    "KeyServerRpcError",
    "TaskTimeoutError",
    "ApplicableRule",
    "Environment",
    "Goal",
    "GoalDiagnostics",
    "GoalRules",
    "Instance",
    "Macro",
    "ProofObligation",
    "SavedProof",
    "Sequent",
    "Statistics",
    "StructuredFormula",
    "StuckPoint",
    "Task",
    "__version__",
]
