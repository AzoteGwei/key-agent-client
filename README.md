# key-agent-client

A Python client for the headless [KeY](https://key-project.org) theorem prover server.

**This is a third-party tool. It is not an official KeY component.**

It talks to a running `keyext.server` over JSON-RPC and does nothing else. It contains no Java,
ships no jar and never starts a JVM: the server is a separate long-lived process, which is the
whole reason it is worth talking to instead of re-running a prover.

## Why a server at all

`key --auto` answers one question — did it close — and answers it from scratch every time. For an
agent writing JML that is close to unusable: loading a real project takes tens of seconds, so the
try-look-fix loop pays for a cold start on every attempt, and when the proof does not close there
is nothing to look at except a count of open goals.

A running server keeps the loaded project warm and can be asked *what* is open, what the sequent
looks like, and which rule wanted to apply and could not.

## Installing

```sh
uv add key-agent-client        # or: pip install key-agent-client
```

No dependencies. Python 3.10 or newer.

## Starting a server

This client does not start one, on purpose: a library that spawns JVMs is a library that owns
processes it cannot supervise. Run it yourself, from the KeY checkout:

```sh
./gradlew :keyext.server:shadowJar
java -jar keyext.server/build/libs/keyext.server-*-exe.jar --port 0 --workspace /path/to/project
```

It publishes its port, so nothing needs to be passed to this client. Servers shut themselves down
after 30 minutes idle unless told otherwise.

The server JDK must include the `java.desktop` module: `key.core` still touches Swing classes in a
few places, so a jlink-trimmed image will not run it.

## What to point `load` at

For a directory of Java sources, pass the directory. For anything that needs a class path, a
custom rule file or a chosen contract, pass the project's own `.key` file instead — those
declarations live in it, not in the sources:

```
\classpath "./jre/";
\javaSource "src";
\include "symbols.key";
```

Loading such a project by its source directory fails with a symbol KeY cannot resolve, which is
accurate but easy to misread as a broken project. KeY's own `case-studies/timsort` is one of
these.

## Library

```python
from keyclient import KeyClient

with KeyClient.discover(workspace="/path/to/project") as key:
    load = key.wait_for_task(key.load("/path/to/project").task_id)
    env = load.result["envId"]

    contract = key.obligations(env)[0].contract_id
    proof = key.start_proof(env, contract)

    key.wait_for_task(key.run_auto(proof).task_id)

    stats = key.statistics(proof)
    if not stats.closed:
        for goal in key.stuck_points(proof):
            for point in goal.stuck_points:
                print(point.reason, point.rule_id, point.source)
```

### What it will not do

- **No retrying and no reconnecting.** A proof is stateful; replaying a request that may already
  have been applied would change a proof twice while the caller believed it changed once. A broken
  connection raises.
- **No verdict of its own.** `Statistics.closed` is the server's answer, which is KeY's
  `Proof.closed()`. Nothing here computes, infers or defaults it. A task reaching `SUCCEEDED` means
  the work finished without throwing — a macro that ends leaving three goals open is a succeeded
  task with three open goals.
- **No JVM management, no jar downloads, no `--force`.**

### What the diagnostics can and cannot tell you

`stuck_points` reports rules that want to apply to a goal and cannot. An empty list is a finding:
nothing is waiting on a specification you could write.

It does not mean the goal is false. It covers KeY's built-in rules — loop invariants, contracts,
one-step simplification — and not its taclets, so a goal left open because the automatic strategy
ran out of moves also comes back with nothing stuck.

`last_search_outcome` is what tells those apart:

```python
for goal in key.stuck_points(proof):
    if goal.stuck_points:
        ...  # a specification is missing; the points say where
    elif goal.prover_out_of_ideas:
        ...  # the prover gave everything: script, solver or interaction
    else:
        ...  # it never finished looking: raise the budget
```

An empty list after `EXHAUSTED` and an empty list after a limit are the same list and opposite
problems.

### Errors

Every failure the server can report has a number. Branch on it, never on message text:

```python
from keyclient import ErrorCode, KeyServerRpcError

try:
    key.sequent(proof, goal_id)
except KeyServerRpcError as error:
    if error.code == ErrorCode.GOAL_NOT_FOUND:
        ...  # the goal closed since it was listed; list them again
    elif error.code == ErrorCode.SCRIPT_ERROR:
        print(error.positions)  # file, line and column KeY found the trouble at
```

## Command line

```sh
key-agent list
key-agent load /path/to/project
key-agent obligations env-1a2b3c4d
key-agent prove env-1a2b3c4d 'Max[Max::max(int,int)].JML normal_behavior operation contract.0'
key-agent explain prf-9f8e7d6c
key-agent script prf-9f8e7d6c 14 'macro "symbex"; smt;'
key-agent watch
```

### Exit status means something

| Status | Meaning |
| --- | --- |
| `0` | the command succeeded **and** the proof is closed |
| `1` | the command succeeded and the proof is **not** closed |
| `2` | the command failed |

`1` is not an error. A script that treats any non-zero status as a broken tool will report
unproved code as a crash; check for `1` explicitly. Commands that do not touch a proof use `0` and
`2` only.

### Output

`--json` writes exactly one JSON object to stdout and nothing else — no banner, no progress, no
trailing note — so the stream stays parseable. Everything meant for a person goes to stderr.

Without `--json` the output is tab-separated lines with no borders, colour or spinners, because
the most likely reader is still a program.

## Licence

MIT. The KeY server it talks to is GPL-2.0-only; this client is a separate program that
communicates with it over a network protocol.
