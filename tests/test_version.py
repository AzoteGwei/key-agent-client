"""One version number, written down twice.

`pyproject.toml` carries the version because the build backend reads it there; `keyclient` carries
it because a caller holding an object wants to ask what it is without going back to the metadata.
Neither is redundant, and nothing but habit keeps them equal — which is exactly the kind of thing
that stays right for six releases and then quietly is not.

The release workflow checks the git tag against `pyproject.toml` alone. This is the other half of
that check: it makes `pyproject.toml` a version the rest of the package agrees with, so the tag
only ever has to agree with one thing.

Both files are read from disk rather than imported. The question is what this checkout says, which
is what gets tagged and built; an installed copy can be a build behind and would answer for that
build instead.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "keyclient" / "__init__.py"

# Read with a regex rather than tomllib: tomllib arrived in 3.11 and this package supports 3.10,
# so a stdlib parser is not there on every interpreter the suite runs under.
PROJECT_VERSION = re.compile(r"^\[project\]$.*?^version = \"([^\"]+)\"$", re.M | re.S)
DUNDER_VERSION = re.compile(r"^__version__ = \"([^\"]+)\"$", re.M)


def find(pattern: re.Pattern[str], path: Path) -> str:
    match = pattern.search(path.read_text(encoding="utf-8"))
    assert match, f"no version found in {path.relative_to(ROOT)}"
    return match.group(1)


def test_pyproject_and_package_agree_on_the_version() -> None:
    project = find(PROJECT_VERSION, PYPROJECT)
    dunder = find(DUNDER_VERSION, INIT)
    assert project == dunder, (
        f"pyproject.toml says {project} and keyclient.__version__ says {dunder}; "
        f"a release tag can only match one of them"
    )
