"""Contract test: router-shim pins its LLM-Router dependency to an immutable ref.

Guards issue #14 -- ``router-shim/package.json`` must reference
``@quantum-l9/llm-router`` by an immutable ref (a full 40-char commit SHA or a
release tag), never the moving ``#main`` branch, so shim builds are reproducible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_PKG = Path("router-shim/package.json")
_DEP = "@quantum-l9/llm-router"

# github:<owner>/<repo>#<ref> where ref is a 40-hex SHA or a vX.Y.Z-style tag.
_IMMUTABLE_REF = re.compile(
    r"^github:Quantum-L9/LLM-Router#(?P<ref>[0-9a-f]{40}|v?\d+(?:\.\d+)*[\w.\-]*)$"
)


def _dep_spec() -> str:
    data = json.loads(_PKG.read_text(encoding="utf-8"))
    return data["dependencies"][_DEP]


def test_router_dep_is_not_a_moving_branch() -> None:
    spec = _dep_spec()
    for moving in ("#main", "#master", "#latest"):
        assert not spec.endswith(moving), f"{_DEP} still pinned to moving ref {spec!r}"


def test_router_dep_is_immutable_ref() -> None:
    spec = _dep_spec()
    match = _IMMUTABLE_REF.match(spec)
    assert match is not None, f"{_DEP} must pin to a 40-char SHA or release tag, got {spec!r}"
    ref = match.group("ref")
    # A bare branch-like word (e.g. 'main') is not an immutable ref.
    assert ref not in {"main", "master", "latest"}


def test_setup_sh_builds_dist_from_pinned_dep() -> None:
    setup = Path("router-shim/setup.sh").read_text(encoding="utf-8")
    # The build step must still compile dist/index.js from the installed dep.
    assert "node_modules/@quantum-l9/llm-router" in setup
    assert "dist/index.js" in setup
    assert "npm run build" in setup
