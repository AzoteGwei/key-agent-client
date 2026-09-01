# Usage guide

How to get from a Java project with JML specifications to a defensible answer about whether it
verifies, and to a useful next step when it does not.

Read the [vocabulary](#vocabulary) first. Every later section depends on the distinctions in it,
and they are the ones people get wrong.

---

## Vocabulary

**The proof is closed, or it is not.** `Statistics.closed` is the server's report of KeY's own
`Proof.closed()`. It is the only thing in this library that means a contract was proved. If you
take one thing from this guide, take that.

**A finished task is not a closed proof.** Slow work — loading, the automatic search, a macro, a
script — returns a `Task` at once and finishes in the background. `task.succeeded` means the work
ran to an end without throwing. A macro that ends leaving three goals open is a succeeded task
with three open goals. To get from a task to a verdict, read `task.statistics.closed`, or ask
`key.statistics(proof_id)`.

**"Nothing is stuck" has two opposite meanings.** `stuck_points` reports rules that wanted to
apply to a goal and could not — a missing loop invariant, an unspecified callee. An empty list is
a real finding *if the prover had actually finished looking*. If it stopped because it ran out of
budget, the same empty list means nothing at all. `GoalDiagnostics.prover_out_of_ideas` (the
search ended `EXHAUSTED`) is what tells them apart. This is the single most misread value in the
whole interface.

**Stuck points cover built-in rules, not taclets.** Loop invariants, contracts, one-step
simplification — yes. The thousands of rewrite rules the strategy applies — no. So a goal left
open because the strategy ran out of moves also comes back with nothing stuck. That is what
`applicable_rules` is for.

**Goal ids move.** A goal id is the node number KeY assigned, and the tree grows underneath you.
Re-read `goals(proof_id)` after every step rather than carrying an id across one.

**`occ` counts from zero.** When a rule matches a sequent in more than one place, naming the rule
alone is ambiguous and KeY refuses it. The script line has to carry an occurrence —
`rule "hide_left" occ=0;`. `applicable_rules` emits the line with the occurrence already in it, so
you rarely have to think about this; when you write one by hand, count from zero.

---

## Installing

```sh
uv add key-agent-client        # or: pip install key-agent-client
```

No dependencies, Python 3.10 or newer. The MCP server is an extra:
`key-agent-client[mcp]`.

## Starting a server

This client does not start one, on purpose: a library that spawns JVMs is a library that owns
processes it cannot supervise. Run it yourself, from a checkout of
[this KeY fork](https://github.com/AzoteGwei/key) — `keyext.server` is not an upstream KeY
component:

```sh
./gradlew :keyext.server:shadowJar
java -Xmx4g -jar keyext.server/build/libs/keyext.server-*-exe.jar \
  --port 0 --workspace /path/to/project
```

**Give it `-Xmx4g`.** KeY is memory-hungry and a real proof will exhaust the default heap part way
through, which looks like a hang or a crash rather than like running out of memory.

`--port 0` lets the OS choose; the server publishes the port it got, so nothing has to be passed
to this client. Servers shut down after 30 minutes idle unless told otherwise.

The server's JDK must include the `java.desktop` module — `key.core` still touches Swing classes
in a few places, so a jlink-trimmed image will not start it.

### Why a server rather than `key --auto`

`key --auto` answers one question, did it close, and answers it from scratch every time. Loading a
real project takes tens of seconds, so a try–look–fix loop pays for a cold start on every attempt,
and when the proof does not close there is nothing to look at but a count of open goals. A running
server keeps the project warm and can be asked *what* is open, what the sequent looks like, and
which rule wanted to apply and could not.

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

---

## The workflow

### 1. Connect

```python
from keyclient import KeyClient

with KeyClient.discover(workspace="/path/to/project") as key:
    ...
```

`discover` finds a server by the record it published, so there is no port to pass around. If
there is no server it raises `InstanceNotFoundError`, whose message is the command to start one.

### 2. Load, and reuse what is loaded

```python
    for env in key.environments():
        print(env.env_id, env.path, env.proof_count)

    load = key.wait_for_task(key.load("/path/to/project").task_id)
    env_id = load.result["envId"]
```

Loading is the expensive step. Check `environments()` before paying for it again.

### 3. Pick something to prove

```python
    for po in key.obligations(env_id):
        print(po.contract_id, po.target_member)

    contract = key.obligations(env_id, target_class="Max")[0].contract_id
```

`contract_id` is KeY's own contract name, spaces and punctuation included. Pass it through
unchanged.

### 4. Prove, and read the verdict from one place

```python
    proof = key.start_proof(env_id, contract)
    key.wait_for_task(key.run_auto(proof, timeout_ms=60_000).task_id)

    stats = key.statistics(proof)
    if stats.closed:
        print("proved")
```

`timeout_ms` is a wall-clock budget. Running out is not a failure: the task still succeeds, and
whatever the search achieved is kept.

### 5. When it did not close, find out which of three things happened

```python
for goal in key.stuck_points(proof):
    if goal.stuck_points:
        for point in goal.stuck_points:
            print(point.reason, point.rule_id, point.source)  # write a specification
    elif goal.prover_out_of_ideas:
        print(goal.goal_id, "needs help by hand")  # script, solver, interaction
    else:
        print(goal.goal_id, "never finished looking")  # raise the budget
```

Those three branches want three different responses, and running the wrong one wastes the loop:
raising a budget that was not the problem, or rewriting a specification that was fine.

### 6. Read the goal

```python
for formula in key.sequent(proof, goal_id, "STRUCTURED").formulas:
    formula.state  # {heapAtPre:=heap || total:=0 || i:=1}
    formula.program  # { try { while (i <= _n) { total += i; i++; } } ... }
    formula.claim  # … \<…\> ( result_sumTo >= 0 & ... )
```

A goal in mid-flight is one formula of several hundred characters whose interesting part is the
last thirty. `STRUCTURED` splits it the way KeY itself does, using the position table KeY builds
while printing — the same one its editor uses to highlight updates and Java blocks — so it cannot
drift from what KeY thinks the formula is. `antecedent` and `succedent` are filled whichever
format you ask for.

### 7. When the prover has given up, do what a person would

```python
    rules = key.applicable_rules(proof, goal_id)
    for rule in rules.rules:
        if rule.applicable_as_is:
            key.wait_for_task(key.apply_script(proof, goal_id, rule.script).task_id)
            break
```

`rule.script` is a ready-to-run proof script line with the occurrence already in it. Rules that
still need a schema variable filled in, and rules the script `rule` command cannot apply at all,
come with no script — they are listed so you know they exist, not so you can paste them.

You can also drive a goal directly:

```python
    key.apply_script(proof, goal_id, 'macro "symbex"; smt;')
```

### 8. Save something anyone can re-check

```python
    saved = key.save_proof(proof, "Max-max.proof")
    print(saved.path, saved.bytes)
```

A proof does not have to be closed to be saved; a partial one reloads to the same partial state.
`as_bundle=True` writes a `.zproof` carrying the sources and specifications with it, which is what
you want if the proof will be opened anywhere but this machine.

---

## What this library will not do

- **No retrying and no reconnecting.** A proof is stateful; replaying a request that may already
  have been applied would change a proof twice while the caller believed it changed once. A broken
  connection raises.
- **No verdict of its own.** Nothing here computes, infers or defaults `closed`.
- **No JVM management, no jar downloads, no `--force`.**

---

## Command line

Every capability above is also a subcommand. The client connects the same way, so a shell loop and
a Python loop can share one warm server.

```sh
key-agent list                    # servers this machine has a record of
key-agent version                 # ask a server what it is
key-agent load /path/to/project
key-agent obligations env-1a2b3c4d
key-agent prove env-1a2b3c4d 'Max[Max::max(int,int)].JML normal_behavior operation contract.0'
key-agent status prf-9f8e7d6c     # is it closed
key-agent goals prf-9f8e7d6c      # what is still open
key-agent sequent prf-9f8e7d6c 14
key-agent explain prf-9f8e7d6c    # why the open goals are not closing
key-agent script prf-9f8e7d6c 14 'macro "symbex"; smt;'
key-agent save prf-9f8e7d6c --bundle
key-agent replay Max-max.proof    # load a saved proof back and check it
key-agent watch                   # task events as the server pushes them
```

Global flags: `--workspace` to prefer the server anchored to a directory, `--instance` to name
one, `--host`/`--port` to skip discovery entirely, `--json` for machine-readable output,
`--rpc-timeout` and `--wait` for the two different waits.

### Exit status means something

| Status | Meaning |
| --- | --- |
| `0` | the command succeeded **and** the proof is closed |
| `1` | the command succeeded and the proof is **not** closed |
| `2` | the command failed |

`1` is not an error. A script that treats any non-zero status as a broken tool will report
unproved code as a crash — check for `1` explicitly. Commands that do not touch a proof use `0`
and `2` only.

### Output

`--json` writes exactly one JSON object to stdout and nothing else: no banner, no progress, no
trailing note, so the stream stays parseable. Everything meant for a person goes to stderr.

Without `--json` the output is tab-separated lines with no borders, colour or spinners, because
the most likely reader is still a program.

---

## Handling errors

Every failure the server can report has a number. Branch on it, never on message text:

```python
from keyclient import ErrorCode, KeyServerRpcError

try:
    key.sequent(proof, goal_id)
except KeyServerRpcError as error:
    if error.code == ErrorCode.GOAL_NOT_FOUND:
        ...  # it closed since you listed it; list the goals again
    elif error.code == ErrorCode.SCRIPT_ERROR:
        print(error.positions)  # file, line and column KeY found the trouble at
```

`TASK_CONFLICT` means something else is already working on that proof — one proof runs one task at
a time.

---

See also: [the API reference](api.md) for the full surface, and [the MCP server](mcp.md) for
handing this to an agent.
