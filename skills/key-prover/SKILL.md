---
name: key-prover
description: Prove JML-specified Java code correct with the KeY theorem prover, and diagnose proofs that do not close. Use when asked to verify, prove, or formally check Java against JML specifications; when a .key, .proof or .zproof file is involved; or when a JML contract needs writing, strengthening, or debugging because a proof is failing.
license: MIT
---

# Proving Java with KeY

KeY proves that Java code satisfies its JML specification. This skill drives it through the
`key-agent` MCP server.

The whole job comes down to one value. **`closed: true` is the only thing that means a contract
was proved.** A tool returning normally means the tool ran. Never report code as verified on any
other basis — not a finished search, not an absent error, not a plausible-looking sequent.

## Before anything else: is there a server?

Call `key_server`. If it reports no server, do not try to work around it — tell the user to start
one and give them the command:

```sh
java -Xmx4g -jar keyext.server-*-exe.jar --port 0 --workspace .
```

The `-Xmx4g` matters. KeY is memory-hungry and a server started without a heap setting dies part
way through a real proof, which looks like a hang rather than like running out of memory.

### Getting the jar

`keyext.server` lives in <https://github.com/AzoteGwei/key> and is not part of upstream KeY. Its
releases carry a prebuilt shadow jar; reach for that first, since building is a Gradle run of
several minutes.

The asset name carries both KeY's version and the server's — `keyext.server-3.1.0-v0.1.0-exe.jar`
— so it cannot be written down in advance. Resolve it from the latest release:

```sh
gh release download --repo AzoteGwei/key --pattern 'keyext.server-*-exe.jar'
```

Or off the public API, which needs neither a token nor `gh`:

```sh
url=$(curl -fsSL https://api.github.com/repos/AzoteGwei/key/releases/latest | python3 -c '
import json, sys
assets = json.load(sys.stdin)["assets"]
print(next(a["browser_download_url"] for a in assets
           if a["name"].startswith("keyext.server-") and a["name"].endswith("-exe.jar")))
')
curl -fsSLO "$url"
```

Match `keyext.server-` and nothing looser. The same release also ships `key-3.1.0-v0.1.0-exe.jar`,
which is the KeY desktop application — three times the size, opens a window, and does not speak
JSON-RPC.

Build it instead when the user wants a change of their own in the server:

```sh
git clone https://github.com/AzoteGwei/key && cd key
./gradlew :keyext.server:shadowJar    # -> keyext.server/build/libs/keyext.server-*-exe.jar
```

Either way, the JDK that runs it must include `java.desktop`. `key.core` still reaches for Swing
in places, so a trimmed jlink image will not start the server.

## The loop

1. **`key_load(path)`** — a directory of Java sources, or the project's own `.key` file when it
   declares a class path or includes. A real project usually does; loading it by its source
   directory then fails with an unresolved symbol, which reads like a broken project but is not.
   Returns the environment and every contract that can be proved.

2. **`key_prove(env, contract_id)`** — starts a proof and runs the automatic search.

3. **Read `closed`.**
   - `true` → the contract holds. Go to step 5.
   - `false` → go to step 4. Say plainly that it did not close. Do not soften it.

4. **`key_inspect(proof_id)`** — this is the step that decides what to do next, and there are
   exactly three answers. Acting on the wrong one wastes the whole loop.

   | What inspect says | What it means | What to do |
   | --- | --- | --- |
   | A specification is missing, with a file and line | KeY needs a loop invariant, or a contract on something being called | Go and read that line. Write the JML. This is a code change, not a prover problem. |
   | The prover ran out of things to try (`EXHAUSTED`) | More time will not help | Apply one of the proof script lines it offers, or `smt;`. See step 4a. |
   | It never finished looking | It only ran out of budget | Re-run `key_prove` with a larger `budget_ms`. |

   4a. **`key_script(proof_id, goal_id, script)`** — `key_inspect` hands back ready-to-run lines
   with occurrence numbers already in them; prefer those over lines you compose. Otherwise
   `macro "symbex";` to push symbolic execution along, or `smt;` to hand the goal to a solver.
   After each script, read `closed` again.

5. **`key_save(proof_id)`** — write the proof out so a person can re-check it. Do this whenever a
   proof closes; a closed proof nobody kept is a result nobody can verify.

## Reading a goal

`key_inspect` lays each goal out in parts rather than as one long formula:

- **assumed** — what holds going in
- **symbolic state** — what is known about the variables at this point
- **still to execute** — the Java that has not run yet
- **must hold** — the claim, once it has

When "still to execute" contains a loop, the usual cause of an open goal is a missing or too-weak
loop invariant. When it contains a call, look for a missing contract on the callee.

## Rules to hold to

- **Never report a verdict from anything but `closed`.** If you have not seen `closed: true` for a
  contract, that contract is not proved. Say "the proof did not close", not "it looks correct".
- **Do not weaken a specification to make a proof close.** A contract that has been narrowed until
  it is provable can be worse than no contract, because it reads as a guarantee. If the only way
  to close a proof is to weaken what is promised, say so and let the user decide.
- **Prove one contract at a time.** A project has many; report each one's outcome separately
  rather than summarising a batch as working.
- **Goal ids move.** They are node numbers, and the tree grows underneath you. Use the
  `openGoalIds` from the most recent answer, never one from an earlier step.
- **An empty stuck-point list is not "the goal is fine".** It means nothing is waiting on a
  specification. Whether that is a finding depends on whether the search had finished looking,
  which is what `key_inspect` tells you.

## When to stop and ask

- The proof needs a specification that would change what the code promises.
- The prover is exhausted and the offered scripts do not close it — say what is open and what you
  tried, rather than trying variations indefinitely.
- The project will not load. That is a class path or `.key` file question, and guessing at paths
  wastes turns.

## More detail

- [Usage guide](../../docs/guide.md) — the same workflow driven by hand
- [MCP tool reference](../../docs/mcp.md) — every tool's inputs and outputs
- [API reference](../../docs/api.md) — for writing Python against the server directly
