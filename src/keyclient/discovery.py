"""Finding a running server without being told where it is.

An instance publishes a record of itself when it starts, under its workspace and under the user's
state directory. Reading those is how a client gets a port that the operating system usually
chose.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .exceptions import InstanceNotFoundError
from .models import Instance

__all__ = [
    "list_instances",
    "resolve",
    "user_state_directory",
    "workspace_directory",
    "START_HINT",
]

WORKSPACE_DIRECTORY = ".keyext-server"
STATE_DIRECTORY = "keyext-server"

#: What to run when no server is there. Kept as a template rather than prose because the caller
#: most likely to read it is an agent, and an agent that is handed a command can fix this itself.
#:
#: The heap setting is not decoration. KeY's own test JVMs are given 4g and its heavier modules
#: 3g; on a real project the default heap runs out, and an OutOfMemoryError part way through a
#: proof search is close to undiagnosable from the outside.
START_HINT = "java -Xmx4g -jar keyext.server-*-exe.jar --port 0 --workspace {workspace}"


def user_state_directory() -> Path:
    """Where instances publish themselves for this user.

    ``XDG_STATE_HOME`` decides it when set, on every platform, so a caller can always say where.
    Otherwise the platform decides: ``%LOCALAPPDATA%`` on Windows, where per-machine state belongs
    and is not roamed to other machines — which matters, since a record naming a port on this
    machine is of no use on another. Elsewhere, the ``~/.local/state`` the XDG specification names
    as its default.

    This has to agree with the server, which chooses the same way; if it did not, the records it
    writes would be looked for somewhere they are not.
    """
    configured = os.environ.get("XDG_STATE_HOME")
    if configured:
        base = Path(configured)
    elif sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        base = Path(local) if local else Path.home() / "AppData" / "Local"
    else:
        base = Path.home() / ".local" / "state"
    return base / STATE_DIRECTORY / "instances"


def workspace_directory(workspace: str | os.PathLike[str]) -> Path:
    """Where instances anchored to a workspace publish themselves."""
    return Path(workspace) / WORKSPACE_DIRECTORY


def list_instances(workspace: str | os.PathLike[str] | None = None) -> list[Instance]:
    """Reads every instance record that can be found.

    :param workspace: also read the registry of this workspace; when omitted only the per-user
        registry is read
    :returns: the records, newest first, each marked with whether its process still exists
    """
    directories = [user_state_directory()]
    if workspace is not None:
        directories.append(workspace_directory(workspace))

    found: dict[str, Instance] = {}
    for directory in directories:
        for record in _read_directory(directory):
            # The same instance is published in both places; either copy will do.
            found.setdefault(record.instance_id, record)
    return sorted(found.values(), key=lambda each: each.started_at, reverse=True)


def resolve(
    workspace: str | os.PathLike[str] | None = None,
    instance_id: str | None = None,
    *,
    include_stale: bool = False,
) -> Instance:
    """Picks the instance to talk to.

    :param workspace: prefer instances anchored to this directory
    :param instance_id: demand this exact instance
    :param include_stale: consider records whose process is gone; almost never what you want
    :returns: the most recently started live instance that matches
    :raises InstanceNotFoundError: when nothing matches, with a command that starts one
    """
    candidates = list_instances(workspace)
    if instance_id is not None:
        candidates = [each for each in candidates if each.instance_id == instance_id]
    if workspace is not None:
        wanted = str(Path(workspace).resolve())
        anchored = [each for each in candidates if _same_path(each.workspace, wanted)]
        # Fall back to any instance rather than none: a server started elsewhere can still load a
        # project by absolute path, and refusing to use it would help nobody.
        candidates = anchored or candidates
    if not include_stale:
        candidates = [each for each in candidates if each.alive]

    if not candidates:
        raise InstanceNotFoundError(_no_instance_message(workspace, instance_id))
    return candidates[0]


def _no_instance_message(workspace: str | os.PathLike[str] | None, instance_id: str | None) -> str:
    where = f" for workspace {Path(workspace).resolve()}" if workspace is not None else ""
    which = f" with id {instance_id}" if instance_id is not None else ""
    command = START_HINT.format(workspace=Path(workspace).resolve() if workspace else ".")
    return (
        f"No running KeY server found{where}{which}.\n"
        f"Start one with:\n"
        f"    {command}\n"
        f"It publishes its port, so nothing else needs to be passed to this client."
    )


def _read_directory(directory: Path) -> list[Instance]:
    if not directory.is_dir():
        return []
    records = []
    for file in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A half-written or hand-edited file costs its own entry, not the whole listing.
            continue
        record = _instance(payload, file)
        if record is not None:
            records.append(record)
    return records


def _instance(payload: dict[str, Any], file: Path) -> Instance | None:
    try:
        pid = int(payload["pid"])
        return Instance(
            instance_id=str(payload["instanceId"]),
            pid=pid,
            host=str(payload.get("host", "127.0.0.1")),
            port=int(payload["port"]),
            workspace=str(payload.get("workspacePath", "")),
            api_version=str(payload.get("apiVersion", "")),
            key_version=str(payload.get("keyVersion", "")),
            threads=int(payload.get("threads", 1)),
            started_at=str(payload.get("startedAt", "")),
            alive=_is_alive(pid),
            record_path=str(file),
            raw=payload,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _is_alive(pid: int) -> bool:
    """Whether a process with that id exists.

    A hint, not a verdict. Process ids are reused, so a stale record can point at an unrelated
    process; a caller that needs certainty connects and compares the instance id.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_process_exists(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # It exists and belongs to somebody else. Existing is what was asked.
        return True
    except (OSError, ValueError):
        return False
    return True


def _windows_process_exists(pid: int) -> bool:
    """Asks Windows whether a process id is in use, without touching the process.

    ``os.kill(pid, 0)`` is the usual way to ask this and must never be used here: on Windows any
    signal other than the two console events is not a signal at all but a call to
    TerminateProcess, so the probe would kill the server it was asked about. Listing what is
    running would stop everything that is running.

    Opening a query handle asks the same question and cannot do anything to the process.
    """
    import ctypes

    # PROCESS_QUERY_LIMITED_INFORMATION: enough to be told the id is in use, and not enough to
    # read, write or end anything.
    query_limited_information = 0x1000
    access_denied = 5

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return True
    # Refused rather than absent: something is there, it is simply not ours to look at.
    return kernel32.GetLastError() == access_denied


def _same_path(left: str, right: str) -> bool:
    try:
        return Path(left).resolve() == Path(right)
    except OSError:
        return left == right
