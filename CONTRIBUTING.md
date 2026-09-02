# Contributing

## Setting up

```sh
uv sync --group dev --extra mcp
```

Everything below assumes that. The library and the command line have no dependencies at all — a
client an agent is expected to install into whatever environment it already has should not bring a
tree with it — so the `mcp` extra is there only because `keyclient.mcp` and its tests need it.

## The checks

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Those three are what `.github/workflows/ci.yml` runs, on Python 3.10 and 3.14: the two ends of the
supported range, because almost everything that breaks in between breaks at one of them.

## Two kinds of test

Most of the suite talks to `FakeServer` in [`tests/conftest.py`](tests/conftest.py), an in-process
JSON-RPC server that answers whatever a test told it to. That is what keeps the protocol tests
fast and hermetic, and it is also exactly their limit: a fake that was told to say `closed: true`
establishes nothing about whether KeY still proves anything.

[`tests/test_acceptance.py`](tests/test_acceptance.py) is the other kind. It talks to a real
server, and skips itself when there is not one:

```sh
gh release download --repo AzoteGwei/key --pattern 'keyext.server-*-exe.jar'
java -Xmx4g -jar keyext.server-*-exe.jar --port 0 --workspace examples/first-proof &
uv run key-agent list          # confirm it published itself before trusting the result
uv run pytest tests/test_acceptance.py
```

That confirmation matters. A skipped test is a green tick over nothing, so CI establishes the
server is up in a step where not finding it fails, and never infers it from pytest's exit status.

## Documentation is checked, not reviewed

[`tests/test_docs.py`](tests/test_docs.py) and [`tests/test_examples.py`](tests/test_examples.py)
fail on prose rather than on code: an exported symbol missing from `docs/api.md`, a subcommand
missing from the guide, an MCP tool missing from `SKILL.md`, a `see also` in `key-agent -h`
pointing at a path nobody kept, a contract id the guide quotes that the example no longer has, a
line number the guide sends you to that has stopped being the loop.

When one of those fails after a rename, the document is the thing to fix. That is the point: a
stale comment is a nuisance, but a stale reference page is what somebody builds against.

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
