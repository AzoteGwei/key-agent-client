# API reference

A map of the library, for someone — or something — about to write code against it.

Every symbol here has a docstring that says more than this page does. This page exists because a
docstring can only be read once you know what to look for, and the hard part of using a prover
through an API is knowing which of thirty methods answers your question. So: one line each, what
it is and when you reach for it.

```python
from keyclient import KeyClient, ErrorCode, KeyServerRpcError
```

Import everything from the `keyclient` package root. The submodules are an implementation detail.

---

## Connecting

| Symbol | What it is |
| --- | --- |
| `KeyClient` | The connection. One instance talks to one server; use it as a context manager. |
| `KeyClient.discover(...)` | The normal way to build one: finds a server by its published record instead of being told a port. |
| `list_instances(workspace=None)` | Every server this machine has a record of. Use it to show the user their options. |
| `resolve(workspace=None, instance_id=None)` | Picks exactly one instance, or raises `InstanceNotFoundError` with the command to start one. |
| `Instance` | One server's record: `host`, `port`, `pid`, `workspace`, `api_version`, `key_version`, `alive`. `.stale` is true when the record outlived its process. |

`KeyClient(host, port)` is there for when you already know the port — a tunnel, a container, a
test. Prefer `discover`.

## Asking what the server is

| Method | Returns | When |
| --- | --- | --- |
| `version()` | `dict` | First call of a session. Check `apiVersion` against what you built for. |
| `health()` | `bool` | Liveness only. |

## Projects

| Method | Returns | When |
| --- | --- | --- |
| `load(path, **options)` | `Task` | Opens a project. Slow — this is the call the warm server exists to avoid repeating. Pass through `classpath`, `boot_class_path`, `includes` as needed. |
| `environments()` | `list[Environment]` | What is already loaded, so you can reuse it instead of loading again. |
| `obligations(env_id, target_class=None)` | `list[ProofObligation]` | What can be proved. `contract_id` from here is what `start_proof` takes. |
| `close_environment(env_id)` | `bool` | Releases the project and every proof under it. |

`load` returns a `Task`, not an environment: pass `task.task_id` to `wait_for_task`, and the
environment id is in `task.result["envId"]`.

## Proofs

| Method | Returns | When |
| --- | --- | --- |
| `start_proof(env_id, contract_id)` | `str` | Opens a proof. Nothing is proved yet. |
| `run_auto(proof_id, timeout_ms=None)` | `Task` | Runs the automatic search. The main event. |
| `statistics(proof_id)` | `Statistics` | **The only place a verdict comes from.** See `Statistics.closed`. |
| `save_proof(proof_id, path=None, as_bundle=False)` | `SavedProof` | Writes the proof out. `as_bundle` carries the sources with it. |
| `load_proof(path)` | `Task` | Replays a saved proof, loading its environment too. |
| `prune(proof_id, node_id)` | `PrunedProof` | Cuts a proof back to a node and reopens it. |
| `close_proof(proof_id)` | `bool` | Releases one proof. |

## Goals

| Method | Returns | When |
| --- | --- | --- |
| `goals(proof_id, include_closed=False)` | `list[Goal]` | What still needs work. Re-read it after every step: goal ids move. |
| `sequent(proof_id, goal_id, fmt="TEXT")` | `Sequent` | Reads a goal. Pass `"STRUCTURED"` if anything is going to parse it. |
| `macros(proof_id)` | `list[Macro]` | What can be run at a goal. |
| `apply_macro(proof_id, macro_id, goal_id=None)` | `Task` | Runs one. Omit `goal_id` for every open goal. |
| `apply_script(proof_id, goal_id, script)` | `Task` | Drives one goal by hand in KeY's proof script syntax. |

## Diagnostics

These only observe. None of them changes a proof.

| Method | Returns | When |
| --- | --- | --- |
| `explain_goal(proof_id, goal_id, max_depth=None)` | `GoalDiagnostics` | Why one goal is not closing. |
| `stuck_points(proof_id, max_depth=None)` | `list[GoalDiagnostics]` | The same for every open goal. Start here when a proof did not close. |
| `applicable_rules(proof_id, goal_id, max_rules=None)` | `GoalRules` | What a person could still apply. Reach for it once `prover_out_of_ideas` is true. |

## Tasks

Anything slow returns a `Task` immediately and finishes in the background.

| Method | Returns | When |
| --- | --- | --- |
| `wait_for_task(task_id, timeout=3600.0)` | `Task` | The one you will actually use. Raises `TaskTimeoutError` on timeout. |
| `task(task_id)` | `Task` | A single poll, if you are driving your own loop. |
| `tasks()` | `list[Task]` | Everything this server has run. |
| `cancel_task(task_id)` | `bool` | Asks a task to stop. `False` means it had already finished. |
| `events(timeout=None)` | `Iterator[dict]` | Task notifications pushed over SSE, if you would rather not poll. |

---

## Result types

All are frozen dataclasses. Every one keeps the server's untouched JSON in `.raw`, so a field this
client does not model yet is still reachable.

### The one that decides things

**`Statistics`** — `closed`, `open_goals`, `nodes`, `branches`, `total_rule_apps`,
`interactive_steps`, `symb_ex_apps`, `smt_solver_apps`, `loop_inv_apps`,
`operation_contract_apps`, `dependency_contract_apps`, `block_loop_contract_apps`,
`auto_mode_time_ms`.

`closed` is the server's report of KeY's own `Proof.closed()`. It is the only value in this
library that means a contract was proved. Nothing here computes it, infers it or defaults it.

### Everything else

| Type | Fields worth knowing |
| --- | --- |
| `Environment` | `env_id`, `path`, `proof_count` |
| `ProofObligation` | `contract_id`, `kind`, `target_class`, `target_member`, `has_existing_proof` |
| `Goal` | `goal_id`, `node_id`, `is_open`, `is_linked`; `.ref` for calls that want a goal reference |
| `Sequent` | `antecedent`, `succedent`, `format`, `formulas` |
| `StructuredFormula` | `side`, `index`, `text`, `state`, `program`, `claim`; `.has_program` |
| `StuckPoint` | `rule_id`, `rule_name`, `position_hint`, `reason`, `source`; `.needs_specification` |
| `GoalDiagnostics` | `goal_id`, `stuck_points`, `truncated`, `last_search_outcome`; `.prover_out_of_ideas` |
| `ApplicableRule` | `rule_id`, `kind`, `occurrences`, `needs_instantiation`, `needs_assumption`, `side`, `index`, `script`; `.applicable_as_is` |
| `GoalRules` | `goal_id`, `rules`, `truncated` |
| `Task` | `task_id`, `kind`, `status`, `subject`, `result`, `progress`, `error`; `.finished`, `.succeeded`, `.statistics` |
| `Macro` | `macro_id`, `name`, `category`, `description` |
| `SavedProof` | `path`, `bytes` |
| `PrunedProof` | `proof_id`, `goal_id`, `removed_nodes`, `statistics` |

### The derived properties, and why they exist

Each one is a question that is easy to get subtly wrong by hand:

- `Task.succeeded` — the work ran to an end. **Not** a proved contract. `Task.statistics` gets you
  to the value that is.
- `GoalDiagnostics.prover_out_of_ideas` — the search ended `EXHAUSTED`, so more time will not
  help. This is what separates an empty `stuck_points` that is a finding from one that is an
  artefact of a budget.
- `ApplicableRule.applicable_as_is` — the rule can be applied by a script exactly as offered, with
  nothing left to fill in.
- `StuckPoint.needs_specification` — a specification is missing, and `source` says where.
- `StructuredFormula.has_program` — the goal still has Java to execute, rather than being purely
  logical.
- `Instance.stale` — the record is there but the process is not.

---

## Errors

| Symbol | What it is |
| --- | --- |
| `KeyClientError` | Base of everything this library raises. |
| `KeyServerRpcError` | The server refused. `.code`, `.message`, `.data`, and `.positions` for the file/line/column KeY objected at. |
| `InstanceNotFoundError` | No server. The message carries the command to start one. |
| `TaskTimeoutError` | `wait_for_task` gave up. The task is still running on the server. |
| `ErrorCode` | The numeric codes, by name. |

Branch on `error.code`, never on message text — the server's own documentation says message text
is for humans and may change.

```python
try:
    key.sequent(proof, goal_id)
except KeyServerRpcError as error:
    if error.code == ErrorCode.GOAL_NOT_FOUND:
        ...  # the goal closed since you listed it; list them again
    elif error.code == ErrorCode.SCRIPT_ERROR:
        print(error.positions)
```

`ErrorCode` members: `PARSE_ERROR`, `INVALID_REQUEST`, `METHOD_NOT_FOUND`, `INVALID_PARAMS`,
`INTERNAL_ERROR`, `ENV_NOT_FOUND`, `PROOF_NOT_FOUND`, `GOAL_NOT_FOUND`, `LOAD_FAILED`,
`SCRIPT_ERROR`, `DIAGNOSTIC_UNAVAILABLE`, `TASK_CONFLICT`, `SOLVER_UNAVAILABLE`,
`UNSUPPORTED_FORMAT`, `TASK_NOT_FOUND`, `SAVE_FAILED`.

## Other

`__version__` — the installed version of this package.

---

See also: [the usage guide](guide.md) for the workflow these fit into, and
[the MCP server](mcp.md) for using the same capability from an agent.
