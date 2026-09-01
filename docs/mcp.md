# MCP server

Hands the KeY prover to an agent as six tools. This is the interface to reach for when a model is
doing the work; if you are writing code yourself, use [the library](api.md) instead.

## Setup

```sh
claude mcp add key-agent -- uvx --from "key-agent-client[mcp]" key-agent-mcp --workspace .
```

Options: `--workspace` (prefer the server anchored to this directory, default cwd), `--instance`
(name one exactly), `--timeout` (seconds to wait for one operation, default 900).

**Start a KeY server first.** This process contains no prover — it connects to a running
`keyext.server`, so the warm JVM outlives the conversation instead of being started and thrown
away with each one:

```sh
java -Xmx4g -jar keyext.server-*-exe.jar --port 0 --workspace .
```

It does not start one for you, and it does not refuse to run without one: the tools resolve a
server on every call, so a server started after the MCP client is still found. When none is
running the tools say so and print the command, `-Xmx4g` included — a server started without a
heap setting dies part way through a real proof.

## The design, in one paragraph

The tools are shaped like the work rather than like the protocol. `key_prove` starts a proof, runs
the search, waits for it and reports the proof, so **no task ever reaches the model**. That is
deliberate. The wire protocol answers a long operation with a handle whose status becomes
`SUCCEEDED`, meaning "the work finished" — one word away from "the contract holds". Waiting inside
the tool means there is no `SUCCEEDED` for a model to misread. What comes back instead is
`closed`, which is KeY's own `Proof.closed()` and the only value here that means anything.

The two tools that run a prover carry that warning in the description a model sees *before* it
calls them, not only in the result.

---

## The tools

### `key_load(path)`

Loads a Java project, a `.key` problem file or a saved `.proof`, and lists what can be proved in
it.

Point it at a directory of Java sources, or at the project's own `.key` file when it declares a
class path or includes — a real project usually does, and loading it by its source directory then
fails with an unresolved symbol.

```
environment: env-1a2b3c4d
1 obligation(s):
  Adder.add(int, int)  [FUNCTIONAL_OPERATION]  Adder[Adder::add(int,int)].JML normal_behavior operation contract.0
```

### `key_prove(env, contract_id, budget_ms=60000)`

Starts a proof for one contract and runs KeY's automatic search.

The budget defaults to a minute, deliberately short: a tool call that blocks for an hour is worse
for an agent than one that comes back and says it needs longer, because the second can be acted
on.

Closed:

```
proof: prf-9f8e7d6c
closed: true — the proof closed. The contract holds.
```

Not closed — and note that the answer distinguishes the two reasons, because they call for
opposite next steps:

```
proof: prf-9f8e7d6c
closed: false — the proof did NOT close. 1 goal(s) remain open.
The prover ran out of things to try, so more time will not help. Use key_inspect to see
what is open, then a proof script, a solver, or a missing specification.

searchEnded: EXHAUSTED
openGoalIds: [30]
```

`openGoalIds` comes back with the verdict because every next step addresses a goal and node
numbers move as a proof grows, so an id fetched a moment earlier may no longer exist.

### `key_inspect(proof_id, max_goals=5)`

Reports why the open goals are not closing.

Each goal is laid out as what is assumed, the symbolic state, the program still to execute, and
what must hold once it has — rather than as one several-hundred-character formula. It then says
which of three situations the goal is in:

- **a specification is missing** — with the file, line and column to go and look at;
- **the prover ran out of things to try** — followed by the proof script lines that could still be
  applied, occurrence numbers included;
- **it never finished looking** — raise the budget.

Rules are offered only where they are the thing left. A rule that still needs a schema variable
filled in is named without a script line, rather than listed alongside as though it were
interchangeable with one you can paste.

### `key_script(proof_id, goal_id, script)`

Applies a KeY proof script to one goal and reports what the proof looks like afterwards.

Scripts are the preferred way to push a proof along: they are reproducible and can be saved next
to the code. Useful commands: `macro "symbex";` to run symbolic execution, `smt;` to hand a goal
to a solver, and the `rule "…" occ=…;` lines `key_inspect` hands back.

### `key_save(proof_id, path=None, as_bundle=False)`

Writes a proof to disk in KeY's own format so it can be reviewed, re-checked by KeY and committed.

Save a proof once it closes. An unclosed proof can be saved too and comes back exactly as
unclosed. A save that fails says `NOT written` and gives the error code — it never reports a file
that is not there.

### `key_server()`

Reports which KeY server this is connected to: instance id, endpoint, workspace, API version and
KeY version.

---

## What the tools will never say

No tool describes an unclosed proof with any of *proved*, *verified*, *success*, *succeeded*,
*holds* or *correct*. That is not a style preference — a model reading any of those words about an
open proof would report unverified code as verified, and it is pinned by a test that asserts none
of them appears.

A tool returning normally means the tool ran. Nothing more.

---

See also: [the usage guide](guide.md) for the same workflow driven by hand, and
[`skills/key-prover`](../skills/key-prover/SKILL.md) for the Claude Code skill that drives these
tools.
