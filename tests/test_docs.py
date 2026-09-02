"""Keeping the documentation and the code the same thing.

Prose rots quietly. A method is renamed, a tool is added, a subcommand is dropped, and the
document that described it goes on describing it — and unlike a stale comment, a stale reference
page is what somebody builds against. The server side of this project holds its OpenRPC document
to the same standard by comparing it against a running dispatcher; these are the client's half of
that, and they exist so that documentation is checked rather than reviewed.

They deliberately assert only that things are *mentioned*. Whether the sentence about a method is
a good sentence is not something a test can know; whether the method is in the reference at all is.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

import keyclient
from keyclient.client import KeyClient

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
SKILL = ROOT / "skills" / "key-prover" / "SKILL.md"
BLOB = "https://github.com/AzoteGwei/key-agent-client/blob/main/"


def read(path: Path) -> str:
    assert path.is_file(), f"{path.relative_to(ROOT)} is missing"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(keyclient.__all__))
def test_every_public_symbol_is_in_the_reference(name: str) -> None:
    # Exported and undocumented is the worst of both: it is supported, and nobody can find it.
    assert name in read(DOCS / "api.md"), f"{name} is exported but not in docs/api.md"


@pytest.mark.parametrize("name", sorted(n for n in keyclient.__all__ if n != "__version__"))
def test_every_public_symbol_says_what_it_is(name: str) -> None:
    doc = (getattr(keyclient, name).__doc__ or "").strip()
    assert doc, f"{name} has no docstring"


@pytest.mark.parametrize(
    "name",
    sorted(
        n for n, f in inspect.getmembers(KeyClient, inspect.isfunction) if not n.startswith("_")
    ),
)
def test_every_client_method_says_what_it_is(name: str) -> None:
    # The reference is a map and points at these; a method whose docstring is empty leaves the
    # reader at the end of the map with nothing there.
    doc = (getattr(KeyClient, name).__doc__ or "").strip()
    assert doc, f"KeyClient.{name} has no docstring"


def test_every_command_line_subcommand_is_in_the_guide() -> None:
    source = (ROOT / "src" / "keyclient" / "cli.py").read_text(encoding="utf-8")
    subcommands = set(re.findall(r'commands\.add_parser\(\s*"([a-z-]+)"', source))
    assert subcommands, "no subcommands found; this test has stopped testing anything"

    guide = read(DOCS / "guide.md")
    undocumented = sorted(c for c in subcommands if f"key-agent {c}" not in guide)
    assert not undocumented, f"subcommands missing from docs/guide.md: {undocumented}"


def test_every_mcp_tool_is_documented_and_in_the_skill() -> None:
    source = (ROOT / "src" / "keyclient" / "mcp.py").read_text(encoding="utf-8")
    tools = set(re.findall(r"def (key_\w+)\(", source))
    assert tools, "no tools found; this test has stopped testing anything"

    reference = read(DOCS / "mcp.md")
    skill = read(SKILL)
    # Both, and for different reasons: the reference is what a person configuring this reads, the
    # skill is what decides whether a model reaches for the tool at all.
    assert not sorted(t for t in tools if t not in reference), "missing from docs/mcp.md"
    assert not sorted(t for t in tools if t not in skill), "missing from SKILL.md"


def test_every_error_code_is_in_the_reference() -> None:
    codes = {n for n in vars(keyclient.ErrorCode) if n.isupper()}
    reference = read(DOCS / "api.md")
    missing = sorted(c for c in codes if c not in reference)
    # Callers are told to branch on these rather than on message text, which only works if the
    # list of them is somewhere findable.
    assert not missing, f"error codes missing from docs/api.md: {missing}"


def test_the_skill_is_installable_where_claude_code_looks_for_it() -> None:
    text = read(SKILL)
    frontmatter = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert frontmatter, "SKILL.md needs YAML frontmatter"

    fields = dict(re.findall(r"^([a-z-]+):\s*(.*)$", frontmatter.group(1), re.M))
    assert "name" in fields and "description" in fields, "name and description are required"
    # A skill is installed by copying its directory, and the name has to match that directory or
    # it is silently not loaded. Nothing about the failure would point here, so it is pinned here.
    assert fields["name"] == SKILL.parent.name, (
        f"frontmatter name {fields['name']!r} must match the directory {SKILL.parent.name!r}"
    )
    assert len(fields["description"]) > 60, "the description decides when the skill is used"


def test_the_documents_reference_each_other_and_nothing_missing() -> None:
    pages = [
        ROOT / "README.md",
        DOCS / "guide.md",
        DOCS / "api.md",
        DOCS / "mcp.md",
        ROOT / "examples" / "first-proof" / "README.md",
        SKILL,
    ]
    for page in pages:
        for link in re.findall(r"\]\(([^)#][^)]*?)(?:#[^)]*)?\)", read(page)):
            if link.startswith(("http://", "https://", "mailto:")):
                continue
            target = (page.parent / link).resolve()
            assert target.exists(), f"{page.name} links to {link}, which does not exist"


def test_the_readme_links_out_absolutely_and_to_files_that_exist() -> None:
    # README is also the long description on PyPI, where a relative link resolves against
    # pypi.org and finds nothing. So its links into the rest of the repository are absolute,
    # which puts them past the check above — and an absolute link to a file somebody moved is
    # exactly as broken as a relative one.
    readme = read(ROOT / "README.md")
    for link in re.findall(r"\]\(([^)#][^)]*?)(?:#[^)]*)?\)", readme):
        assert link.startswith(("http://", "https://", "mailto:")), (
            f"README links to {link} relatively; on PyPI that resolves against pypi.org"
        )
    for path in re.findall(re.escape(BLOB) + r"([^)\s#]+)", readme):
        assert (ROOT / path).exists(), f"README links to {path}, which does not exist"
