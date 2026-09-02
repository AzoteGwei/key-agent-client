"""The ``key-agent`` command line.

Three rules shape everything here.

*Exit codes carry meaning.* ``0`` is the operation succeeded **and** the proof is closed, ``1`` is
the operation succeeded and the proof is **not** closed, ``2`` is the operation failed. A caller
that only checks for a non-zero status will treat an unproved proof as a broken tool, which is the
right way round: the two are different, and neither is success. Commands that do not touch a proof
use ``0`` and ``2`` only.

*``--json`` means only JSON.* One object on stdout and nothing else — no banner, no progress, no
trailing note. Everything a person would want to read goes to stderr, so a pipe stays parseable.

*Human output is still for machines.* Concise lines with no table borders, no spinners and no
colour, because the most likely reader is a program that will grep it.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from . import __version__
from .client import KeyClient
from .discovery import list_instances
from .exceptions import InstanceNotFoundError, KeyClientError, KeyServerRpcError, TaskTimeoutError
from .models import Task

EXIT_CLOSED = 0
EXIT_NOT_CLOSED = 1
EXIT_FAILED = 2

#: What `-h` says exists besides this command.
#:
#: A manual page would call it SEE ALSO. It is here for the same reason `InstanceNotFoundError`
#: carries a command rather than a description: the reader most likely to run `key-agent -h` is an
#: agent that has just been handed this tool and has nothing else to go on, and neither the MCP
#: server nor the skill file announces itself from inside a shell.
#:
#: Named by what they are rather than by whose harness they suit. The skill file's format belongs
#: to somebody else and may be renamed; what this command promises is that a file is there. The
#: MCP server is written out as the command that installs and starts it, because `key-agent-mcp`
#: on its own reads like a package to go and find, and there is no such package: it is a script
#: this one ships, and serving needs the extra.
SEE_ALSO = """see also:
  the same prover as MCP tools rather than as subcommands, from this package's
  mcp extra:
    uvx --from "key-agent-client[mcp]" key-agent-mcp --workspace .

  a skill file, for an agent harness that reads them:
    https://github.com/AzoteGwei/key-agent-client/blob/main/skills/key-prover/SKILL.md

  three contracts whose answers are already known, for checking a setup:
    https://github.com/AzoteGwei/key-agent-client/tree/main/examples/first-proof"""


def main(argv: list[str] | None = None) -> int:
    """Runs the command line.

    :returns: the process exit status, meaning what the module docstring says it means
    """
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help(sys.stderr)
        return EXIT_FAILED
    try:
        return args.handler(args)
    except InstanceNotFoundError as error:
        # The message carries a command that starts a server. It goes to stderr even under
        # --json, because it is advice for whoever is reading, not a result.
        print(str(error), file=sys.stderr)
        _emit_failure(args, "no-instance", str(error))
        return EXIT_FAILED
    except KeyServerRpcError as error:
        print(f"error: {error.message} (code {error.code})", file=sys.stderr)
        for position in error.positions:
            print(
                f"  at {position.get('file', '?')}:{position.get('line', 0)}"
                f":{position.get('column', 0)}: {position.get('message', '')}",
                file=sys.stderr,
            )
        _emit_failure(args, error.code, error.message, error.data)
        return EXIT_FAILED
    except (KeyClientError, TaskTimeoutError) as error:
        print(f"error: {error}", file=sys.stderr)
        _emit_failure(args, "client-error", str(error))
        return EXIT_FAILED
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return EXIT_FAILED


# -- commands -----------------------------------------------------------------------------


def _list(args: argparse.Namespace) -> int:
    instances = list_instances(args.workspace)
    if args.json:
        _json({"instances": [_instance_json(each) for each in instances]})
        return EXIT_CLOSED
    if not instances:
        print("no instances", file=sys.stderr)
        return EXIT_CLOSED
    for each in instances:
        state = "stale" if each.stale else "alive"
        print(
            f"{each.instance_id}\t{state}\t{each.host}:{each.port}\tpid={each.pid}\t{each.workspace}"
        )
    return EXIT_CLOSED


def _version(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        payload = client.version()
    if args.json:
        _json(payload)
    else:
        for key, value in payload.items():
            print(f"{key}\t{value}")
    return EXIT_CLOSED


def _load(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        task = _await(client, client.load(args.path), args)
        if not task.succeeded:
            return _report_failed_task(task, args)
        env_id = (task.result or {}).get("envId", "")
        if args.json:
            _json({"envId": env_id, "task": task.raw})
        else:
            print(f"env\t{env_id}")
    return EXIT_CLOSED


def _obligations(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        found = client.obligations(
            args.env, args.target_class, include_library_classes=args.include_library_classes
        )
    if args.json:
        _json({"obligations": [each.raw for each in found]})
        return EXIT_CLOSED
    for each in found:
        proved = "proved" if each.has_existing_proof else "open"
        print(
            f"{each.target_class}\t{each.target_member}\t{each.kind}\t{proved}\t{each.contract_id}"
        )
    return EXIT_CLOSED


def _prove(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        proof_id = client.start_proof(args.env, args.contract)
        task = _await(client, client.run_auto(proof_id, args.timeout_ms), args)
        if not task.succeeded:
            return _report_failed_task(task, args, proof_id=proof_id)
        # Asked of the proof, not concluded from the task having finished.
        statistics = client.statistics(proof_id)
        outcome = (task.result or {}).get("outcome", "")

    if args.json:
        _json({"proofId": proof_id, "outcome": outcome, "statistics": statistics.raw})
    else:
        print(f"proof\t{proof_id}")
        print(f"outcome\t{outcome}")
        print(f"closed\t{str(statistics.closed).lower()}")
        print(f"openGoals\t{statistics.open_goals}")
    return EXIT_CLOSED if statistics.closed else EXIT_NOT_CLOSED


def _status(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        statistics = client.statistics(args.proof)
    if args.json:
        _json(statistics.raw)
    else:
        for key, value in statistics.raw.items():
            print(f"{key}\t{json.dumps(value) if isinstance(value, bool) else value}")
    return EXIT_CLOSED if statistics.closed else EXIT_NOT_CLOSED


def _goals(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        found = client.goals(args.proof)
    if args.json:
        _json({"goals": [each.raw for each in found]})
        return EXIT_CLOSED
    for each in found:
        linked = "linked" if each.is_linked else "-"
        print(f"{each.goal_id}\t{'open' if each.is_open else 'closed'}\t{linked}")
    return EXIT_CLOSED


def _sequent(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        sequent = client.sequent(args.proof, args.goal, args.format)
    if args.json:
        _json(sequent.raw)
        return EXIT_CLOSED
    if not sequent.formulas:
        for formula in sequent.antecedent:
            print(f"A\t{_one_line(formula)}")
        for formula in sequent.succedent:
            print(f"S\t{_one_line(formula)}")
        return EXIT_CLOSED
    # Still one record per line, so it stays greppable; the tag says which piece.
    for formula in sequent.formulas:
        tag = "A" if formula.side == "ANTECEDENT" else "S"
        if formula.state:
            print(f"{tag}.state\t{_one_line(formula.state)}")
        if formula.program:
            print(f"{tag}.program\t{_one_line(formula.program)}")
        print(f"{tag}.claim\t{_one_line(formula.claim)}")
    return EXIT_CLOSED


def _explain(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        per_goal = client.stuck_points(args.proof, args.max_depth)
    if args.json:
        _json({"goals": [each.raw for each in per_goal]})
        return EXIT_CLOSED
    for goal in per_goal:
        if not goal.stuck_points:
            # Not an absence of information. No rule is waiting on anything, so the goal is not
            # under-specified and the specification or the code is the thing to look at.
            print(
                f"{goal.goal_id}\tno-rule-applies\t"
                f"nothing is waiting on a specification; the goal is likely not provable"
            )
            continue
        for point in goal.stuck_points:
            source = point.source or {}
            where = (
                f"{source.get('file', '')}:{source.get('line', 0)}"
                if source
                else point.position_hint
            )
            print(f"{goal.goal_id}\t{point.reason}\t{point.rule_id}\t{where}")
        if goal.truncated:
            print(
                f"{goal.goal_id}\ttruncated\tthe probe stopped before the end of the formula",
                file=sys.stderr,
            )
    return EXIT_CLOSED


def _script(args: argparse.Namespace) -> int:
    source = args.script if args.script is not None else sys.stdin.read()
    with _connect(args) as client:
        task = _await(client, client.apply_script(args.proof, args.goal, source), args)
        if not task.succeeded:
            return _report_failed_task(task, args, proof_id=args.proof)
        statistics = client.statistics(args.proof)
    if args.json:
        _json({"proofId": args.proof, "statistics": statistics.raw})
    else:
        print(f"closed\t{str(statistics.closed).lower()}")
        print(f"openGoals\t{statistics.open_goals}")
    return EXIT_CLOSED if statistics.closed else EXIT_NOT_CLOSED


def _save(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        saved = client.save_proof(args.proof, args.path, as_bundle=args.bundle)
        # Asked of the proof after writing it, so the status still reports the proof rather than
        # the file operation.
        statistics = client.statistics(args.proof)
    if args.json:
        _json({"path": saved.path, "bytes": saved.bytes, "statistics": statistics.raw})
    else:
        print(f"path\t{saved.path}")
        print(f"bytes\t{saved.bytes}")
        print(f"closed\t{str(statistics.closed).lower()}")
    return EXIT_CLOSED if statistics.closed else EXIT_NOT_CLOSED


def _replay(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        task = _await(client, client.load_proof(args.path), args)
        if not task.succeeded:
            return _report_failed_task(task, args)
        proof_id = (task.result or {})["proof"]["proofId"]
        statistics = client.statistics(proof_id)
    if args.json:
        _json({"proofId": proof_id, "statistics": statistics.raw})
    else:
        print(f"proof\t{proof_id}")
        print(f"closed\t{str(statistics.closed).lower()}")
        print(f"openGoals\t{statistics.open_goals}")
    return EXIT_CLOSED if statistics.closed else EXIT_NOT_CLOSED


def _watch(args: argparse.Namespace) -> int:
    with _connect(args) as client:
        for notification in client.events():
            if args.json:
                print(json.dumps(notification, separators=(",", ":")), flush=True)
            else:
                params = notification.get("params", {})
                print(
                    f"{notification.get('method', '')}\t{params.get('taskId', '')}"
                    f"\t{params.get('status', '')}",
                    flush=True,
                )
    return EXIT_CLOSED


# -- plumbing -----------------------------------------------------------------------------


def _connect(args: argparse.Namespace) -> KeyClient:
    if args.port is not None:
        return KeyClient(args.host, args.port, timeout=args.rpc_timeout)
    return KeyClient.discover(args.workspace, args.instance, timeout=args.rpc_timeout)


def _await(client: KeyClient, task: Task, args: argparse.Namespace) -> Task:
    # Announced on stderr in every mode. --json keeps stdout pure; it does not mean going quiet,
    # and a caller watching a proof search that takes minutes should be told it started.
    print(f"task\t{task.task_id}\t{task.kind}", file=sys.stderr)
    return client.wait_for_task(task.task_id, timeout=args.wait)


def _report_failed_task(task: Task, args: argparse.Namespace, proof_id: str | None = None) -> int:
    error = task.error or {}
    print(f"task {task.task_id} {task.status.lower()}: {error.get('detail', '')}", file=sys.stderr)
    for position in error.get("positions") or []:
        print(
            f"  at {position.get('file', '?')}:{position.get('line', 0)}"
            f":{position.get('column', 0)}: {position.get('message', '')}",
            file=sys.stderr,
        )
    if args.json:
        payload: dict[str, Any] = {"task": task.raw}
        if proof_id is not None:
            payload["proofId"] = proof_id
        _json(payload)
    return EXIT_FAILED


def _emit_failure(args: argparse.Namespace, code: Any, message: str, data: Any = None) -> None:
    """Writes the single JSON object a failed ``--json`` run still owes its caller."""
    if not getattr(args, "json", False):
        return
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if data:
        payload["error"]["data"] = data
    _json(payload)


def _json(payload: Any) -> None:
    json.dump(payload, sys.stdout, indent=None, separators=(",", ":"))
    sys.stdout.write("\n")


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _instance_json(instance: Any) -> dict[str, Any]:
    return {**instance.raw, "alive": instance.alive, "recordPath": instance.record_path}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="key-agent",
        description=(
            "Talk to a running headless KeY server. Third-party tool, not part of the KeY\n"
            "project. Exit status: 0 the proof is closed, 1 it is not, 2 the command failed."
        ),
        epilog=SEE_ALSO,
        # Both blocks are laid out here rather than reflowed to the terminal, which would run the
        # URLs together with the lines describing them.
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"key-agent-client {__version__}")
    parser.add_argument("--host", default="127.0.0.1", help="host of an explicit server")
    parser.add_argument(
        "--port", type=int, default=None, help="port of an explicit server; skips discovery"
    )
    parser.add_argument("--instance", default=None, help="connect to this instance id")
    parser.add_argument(
        "--workspace", default=None, help="prefer the server anchored to this directory"
    )
    parser.add_argument(
        "--json", action="store_true", help="write one JSON object to stdout and nothing else"
    )
    parser.add_argument(
        "--rpc-timeout",
        type=float,
        default=30.0,
        help="seconds to wait for a single request (default: %(default)s)",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=3600.0,
        help="seconds to wait for a task to finish (default: %(default)s)",
    )

    commands = parser.add_subparsers(dest="command")

    listed = commands.add_parser("list", help="list servers this machine has a record of")
    listed.set_defaults(handler=_list)

    version = commands.add_parser("version", help="ask a server what it is")
    version.set_defaults(handler=_version)

    load = commands.add_parser("load", help="load a project or file")
    load.add_argument("path")
    load.set_defaults(handler=_load)

    obligations = commands.add_parser("obligations", help="list what can be proved")
    obligations.add_argument("env")
    obligations.add_argument("--target-class", default=None)
    obligations.add_argument(
        "--include-library-classes",
        action="store_true",
        help="also list the JDK stub contracts KeY loads",
    )
    obligations.set_defaults(handler=_obligations)

    prove = commands.add_parser("prove", help="start a proof and run the automatic search")
    prove.add_argument("env")
    prove.add_argument("contract")
    prove.add_argument(
        "--timeout-ms", type=int, default=None, help="wall-clock budget for the search"
    )
    prove.set_defaults(handler=_prove)

    status = commands.add_parser("status", help="report whether a proof is closed")
    status.add_argument("proof")
    status.set_defaults(handler=_status)

    goals = commands.add_parser("goals", help="list the open goals of a proof")
    goals.add_argument("proof")
    goals.set_defaults(handler=_goals)

    sequent = commands.add_parser("sequent", help="print the sequent of one goal")
    sequent.add_argument("proof")
    sequent.add_argument("goal", type=int)
    sequent.add_argument(
        "--format",
        default="TEXT",
        choices=["TEXT", "UNICODE", "STRUCTURED"],
        help="STRUCTURED splits each formula into state, program and claim",
    )
    sequent.set_defaults(handler=_sequent)

    explain = commands.add_parser("explain", help="report why the open goals are not closing")
    explain.add_argument("proof")
    explain.add_argument("--max-depth", type=int, default=None)
    explain.set_defaults(handler=_explain)

    script = commands.add_parser("script", help="apply a proof script to a goal")
    script.add_argument("proof")
    script.add_argument("goal", type=int)
    script.add_argument(
        "script", nargs="?", default=None, help="the script source; read from stdin when omitted"
    )
    script.set_defaults(handler=_script)

    save = commands.add_parser("save", help="write a proof to disk")
    save.add_argument("proof")
    save.add_argument(
        "path",
        nargs="?",
        default=None,
        help="where to write it; omitted names it after itself in the workspace",
    )
    save.add_argument("--bundle", action="store_true", help="write a .zproof carrying the sources")
    save.set_defaults(handler=_save)

    replay = commands.add_parser("replay", help="load a saved proof back and check it")
    replay.add_argument("path")
    replay.set_defaults(handler=_replay)

    watch = commands.add_parser("watch", help="print task events as the server pushes them")
    watch.set_defaults(handler=_watch)

    return parser


if __name__ == "__main__":
    sys.exit(main())
