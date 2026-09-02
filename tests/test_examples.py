"""Keeping the worked example and the guide the same thing.

``tests/test_docs.py`` checks that the reference pages mention what the code exposes. This is the
other half: ``examples/first-proof`` exists to be the one target whose answers are already known,
which it only is for as long as the commands printed beside it still name the classes, the
contracts and the lines that are actually there. A renamed method or a line that moved turns the
guide from a thing to copy into a thing to debug, and nothing about that failure would point here.

Nothing here starts a JVM. What the example *proves* is pinned in ``test_acceptance.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "first-proof"
GUIDE = ROOT / "docs" / "guide.md"
TUTORIAL = EXAMPLE / "README.md"

#: ``Max[Max::max(int,int)].JML normal_behavior operation contract.0`` and its two neighbours.
CONTRACT = re.compile(r"(\w+)\[(\w+)::(\w+)\(([^)]*)\)\]\.JML")


def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def prose() -> str:
    """Everything that prints commands to copy: the guide and the example's own walk-through."""
    return guide() + TUTORIAL.read_text(encoding="utf-8")


def sources() -> list[Path]:
    return sorted(EXAMPLE.glob("*.java"))


def jml_of(path: Path) -> str:
    """The specification block, which is the part of the pair that has to match."""
    block = re.search(r"/\*@.*?@\*/", path.read_text(encoding="utf-8"), re.S)
    assert block, f"{path.name} has no JML block"
    return block.group(0)


def test_the_example_is_three_classes() -> None:
    # One load, three contracts, three outcomes. A fourth file would be an outcome nobody
    # documented; a missing one would be a section of the guide that cannot be run.
    assert [each.name for each in sources()] == ["BrokenMax.java", "Max.java", "Summer.java"]


def test_the_pair_differs_only_in_the_body() -> None:
    # The whole value of BrokenMax is that its specification is Max's. If the two drift apart,
    # "anything that reports the same verdict for both is broken" stops being true, and the
    # example quietly stops testing the thing it exists to test.
    assert jml_of(EXAMPLE / "Max.java") == jml_of(EXAMPLE / "BrokenMax.java")


@pytest.mark.parametrize("name", [each.name for each in sources()])
def test_every_class_is_walked_through_in_the_guide(name: str) -> None:
    assert name[: -len(".java")] in guide(), f"{name} is in the example but not in docs/guide.md"


def test_every_contract_quoted_anywhere_exists_in_the_example() -> None:
    quoted = set(CONTRACT.findall(prose()))
    assert quoted, "no contract ids found; this test has stopped testing anything"

    for owner, klass, method, _parameters in quoted:
        source = EXAMPLE / f"{klass}.java"
        if not source.is_file():
            continue  # a contract from some other project, quoted to show the shape
        assert owner == klass, f"{owner}[{klass}::…] names two different classes"
        text = source.read_text(encoding="utf-8")
        assert f"{method}(" in text, (
            f"the guide quotes {klass}::{method}, which is not in {source.name}"
        )


def test_the_line_the_guide_sends_you_to_is_still_the_loop() -> None:
    # The point of NEEDS_SPEC is that it hands over a line to go and open. A guide that prints a
    # line number for a line that has moved teaches the opposite of what it is there to teach.
    quoted = re.findall(r"Summer\.java:(\d+)", prose())
    assert quoted, "the guide no longer shows where the missing invariant is"

    lines = (EXAMPLE / "Summer.java").read_text(encoding="utf-8").splitlines()
    for number in {int(each) for each in quoted}:
        assert "while" in lines[number - 1], (
            f"a document points at Summer.java:{number}, which is no longer the loop"
        )
