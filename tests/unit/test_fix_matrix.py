from pathlib import Path

import pytest

from pr_repair.errors import RepoContextError
from pr_repair.routing.fix_matrix import load_fix_matrix
from pr_repair.types import Finding, Severity, SourceName

_MATRIX = """
version: 3
no_match_behavior: propose_only
rules:
  - match: { rule_id: "l9.rename" }
    strategy: { kind: deterministic, handler: exact_suggestion }
  - match: { tool: copilot, tag: style }
    strategy: { kind: deterministic, handler: exact_suggestion }
  - match: { category: architecture_boundary_violation }
    strategy: { kind: llm, task_type: code_generation, tier: opus, depth: high }
  - match: { complexity: medium }
    strategy: { kind: llm, task_type: code_generation, tier: mistral-large, depth: medium }
  - match: { "*": true }
    strategy: { kind: llm, task_type: code_generation, tier: haiku, depth: low }
"""


def _matrix(tmp_path: Path):
    path = tmp_path / "fix_matrix.yaml"
    path.write_text(_MATRIX, encoding="utf-8")
    return load_fix_matrix(path)


def _finding(**kw) -> Finding:
    base = dict(
        finding_id="f",
        pr_number=1,
        source_name=SourceName.agent_review,
        source_priority=110,
        severity=Severity.medium,
        category="review_comment",
        message="m",
        fingerprint="fp",
    )
    base.update(kw)
    return Finding(**base)


def test_version_is_loaded(tmp_path: Path) -> None:
    assert _matrix(tmp_path).version == 3


def test_rule_id_beats_category_and_tag(tmp_path: Path) -> None:
    registry = _matrix(tmp_path)
    f = _finding(
        rule_id="l9.rename",
        tool="copilot",
        tags=["style"],
        category="architecture_boundary_violation",
    )
    strategy = registry.resolve(f)
    assert strategy.kind == "deterministic"
    assert strategy.matched_by == "rule_id"


def test_tag_beats_category(tmp_path: Path) -> None:
    registry = _matrix(tmp_path)
    f = _finding(tool="copilot", tags=["style"], category="architecture_boundary_violation")
    strategy = registry.resolve(f)
    assert strategy.matched_by == "tag"
    assert strategy.kind == "deterministic"


def test_category_match_selects_llm_tier(tmp_path: Path) -> None:
    registry = _matrix(tmp_path)
    f = _finding(category="architecture_boundary_violation", severity=Severity.high)
    strategy = registry.resolve(f)
    assert strategy.matched_by == "category"
    assert strategy.tier == "opus" and strategy.depth == "high"


def test_complexity_only_match(tmp_path: Path) -> None:
    registry = _matrix(tmp_path)
    f = _finding(category="unmapped_category", severity=Severity.medium)
    strategy = registry.resolve(f)
    assert strategy.tier == "mistral-large" and strategy.depth == "medium"


def test_wildcard_fallback(tmp_path: Path) -> None:
    registry = _matrix(tmp_path)
    f = _finding(category="unmapped", severity=Severity.low)  # complexity low -> only wildcard
    strategy = registry.resolve(f)
    assert strategy.matched_by == "wildcard"
    assert strategy.tier == "haiku"


def test_no_match_behavior_when_no_rules(tmp_path: Path) -> None:
    path = tmp_path / "m.yaml"
    path.write_text("version: 1\nno_match_behavior: propose_only\nrules: []\n", encoding="utf-8")
    strategy = load_fix_matrix(path).resolve(_finding(severity=Severity.low))
    assert strategy.kind == "propose_only"


def test_missing_version_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "m.yaml"
    path.write_text("no_match_behavior: propose_only\nrules: []\n", encoding="utf-8")
    with pytest.raises(RepoContextError, match="version"):
        load_fix_matrix(path)


def test_committed_matrix_loads_and_has_version() -> None:
    registry = load_fix_matrix()  # contracts/fix_matrix.yaml
    assert isinstance(registry.version, int) and registry.version >= 1
