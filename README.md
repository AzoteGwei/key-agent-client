# key-agent-client

A Python client for the headless [KeY](https://github.com/AzoteGwei/key) theorem prover server — for
proving that Java code satisfies its JML specification, and for finding out what to do when it
does not.

**This is a third-party tool. It is not an official KeY component.**

It talks to a running `keyext.server` over JSON-RPC and does nothing else. It contains no Java,
ships no jar and never starts a JVM: the server is a separate long-lived process, which is the
whole reason it is worth talking to instead of re-running a prover from cold on every attempt.

## Install

```sh
uv add key-agent-client        # or: pip install key-agent-client
```

No dependencies. Python 3.10 or newer. Add the `[mcp]` extra for the MCP server.

## Start a server

This client does not start one, on purpose: a library that spawns JVMs is a library that owns
processes it cannot supervise. From a checkout of [this KeY fork](https://github.com/AzoteGwei/key),
which is where `keyext.server` lives — it is not part of upstream KeY:

```sh
./gradlew :keyext.server:shadowJar
java -Xmx4g -jar keyext.server/build/libs/keyext.server-*-exe.jar \
  --port 0 --workspace /path/to/project
```

Give it `-Xmx4g`. KeY is memory-hungry and the default heap will not survive a real proof. The
server publishes the port it got, so nothing needs to be passed to this client.

## Prove something

```python
from keyclient import KeyClient

with KeyClient.discover(workspace="/path/to/project") as key:
    load = key.wait_for_task(key.load("/path/to/project").task_id)
    env = load.result["envId"]

    contract = key.obligations(env)[0].contract_id
    proof = key.start_proof(env, contract)
    key.wait_for_task(key.run_auto(proof, timeout_ms=60_000).task_id)

    stats = key.statistics(proof)
    print("closed" if stats.closed else f"{stats.open_goals} goal(s) still open")
```

Or from a shell:

```sh
key-agent load /path/to/project
key-agent prove env-1a2b3c4d 'Max[Max::max(int,int)].JML normal_behavior operation contract.0'
key-agent explain prf-9f8e7d6c
```

## The one thing to know

`Statistics.closed` is the server's report of KeY's own `Proof.closed()`. It is the only value in
this library that means a contract was proved. Nothing here computes it, infers it or defaults it.

In particular a *finished task is not a closed proof*: slow work returns a handle whose status
becomes `SUCCEEDED`, meaning the work ran to an end. A macro that ends leaving three goals open is
a succeeded task with three open goals.

## Where to go next

| If you want to | Read |
| --- | --- |
| Drive the prover yourself, from Python or the shell | [Usage guide](docs/guide.md) |
| Look up a method, a field or an error code | [API reference](docs/api.md) |
| Give an agent the prover over MCP | [MCP server](docs/mcp.md) |
| Install the Claude Code skill | [`skills/key-prover`](skills/key-prover/SKILL.md) |

The guide's [vocabulary section](docs/guide.md#vocabulary) is worth five minutes before anything
else: the distinctions in it — finished versus closed, out of ideas versus out of budget — are the
ones that get misread.

## Releasing

Releases are cut by tag, and only a tag on `main` publishes anything.

1. Set the version in `pyproject.toml` and `src/keyclient/__init__.py`. `tests/test_version.py`
   fails if they disagree.
2. Merge that to `main`.
3. `git tag -a v0.1.0 -m "…" && git push origin v0.1.0`.

`.github/workflows/release.yml` then refuses the tag unless its commit is on `main` and its name
matches `pyproject.toml`, builds, uploads to PyPI through a trusted publisher — no API token
exists for this project — and opens a GitHub release with the wheel, the sdist and a summary. Both
the PyPI upload and the attached files are attested; the release notes say how to check them.

## Licence

MIT. The KeY server it talks to is GPL-2.0-only; this client is a separate program that
communicates with it over a network protocol.
