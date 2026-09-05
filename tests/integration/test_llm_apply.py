import subprocess
from pathlib import Path

import pytest

from pr_repair.config import AppConfig
from pr_repair.llm.contract import ProposedPatch
from pr_repair.repair.llm_apply import apply_llm_proposals, is_apply_eligible
from pr_repair.types import (
    ExecutionMode,
    Finding,
    PRRef,
    ReviewDisposition,
    Severity,
    SourceName,
    TierLevel,
)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path, content: str = "OLD\n") -> Path:
    _run(["git", "init"], tmp_path)
    _run(["git", "config", "user.email", "t@e.com"], tmp_path)
    _run(["git", "config", "user.name", "T"], tmp_path)
    _run(["git", "config", "commit.gpgsign", "false"], tmp_path)
    (tmp_path / "f.py").write_text(content, encoding="utf-8")
    (tmp_path / "a.py").write_text("base\n", encoding="utf-8")
    _run(["git", "add", "-A"], tmp_path)
    _run(["git", "commit", "-m", "init"], tmp_path)
    _run(["git", "checkout", "-b", "fix-branch"], tmp_path)
    return tmp_path


def _pr() -> PRRef:
    return PRRef(
        repo_owner="o",
        repo_name="r",
        pr_number=5,
        title="t",
        head_branch="fix-branch",
        base_branch="main",
        head_sha="s",
        is_draft=False,
        author="a",
        labels=[],
    )


def _finding(category: str = "compliance_failure", **over) -> Finding:
    base = dict(
        finding_id="mr-1",
        pr_number=5,
        source_name=SourceName.agent_review,
        source_priority=110,
        severity=Severity.high,
        category=category,
        message="m",
        file_path="f.py",
        line_start=1,
        line_end=1,
        review_disposition=ReviewDisposition.manual_review,
        repairable=False,
        fingerprint="fp-1",
        tier_impact=TierLevel.t0,
    )
    base.update(over)
    return base if isinstance(base, Finding) else Finding(**base)


def _proposal(replacement: str, expected_block: list[str] | None = None) -> ProposedPatch:
    """Build an LLM proposal.

    ``expected_block`` is mandatory for ``replace_range`` -- the applier refuses
    an unguarded range replacement. The proposer reads it from disk; here the
    default matches `_repo`'s ``f.py``, which the rollback path restores between
    attempts.
    """
    return ProposedPatch(
        finding_id="mr-1",
        file_path="f.py",
        abstained=False,
        instruction={
            "op": "replace_range",
            "file_path": "f.py",
            "line_start": 1,
            "line_end": 1,
            "replacement": replacement,
            "finding_id": "mr-1",
            "expected_block": ["OLD"] if expected_block is None else expected_block,
        },
    )


def _config(tmp_path: Path, verify: list[str]) -> AppConfig:
    return AppConfig(
        github_token="t",
        github_repository="o/r",
        verify_command=verify,
        mode=ExecutionMode.repair_and_verify,
        output_dir=tmp_path / "out",
        write_ceiling=TierLevel.t1,
    )


_CHECK_GOOD = [
    "python",
    "-c",
    "import sys,pathlib; sys.exit(0 if 'GOOD' in pathlib.Path('f.py').read_text() else 1)",
]


# --- eligibility -----------------------------------------------------------


def test_eligibility_gates() -> None:
    wc = TierLevel.t1
    assert is_apply_eligible(_finding(), _proposal("GOOD"), wc) is True
    assert (
        is_apply_eligible(_finding(), ProposedPatch(finding_id="mr-1", abstained=True), wc) is False
    )
    assert (
        is_apply_eligible(_finding(), ProposedPatch(finding_id="mr-1", abstained=False), wc)
        is False
    )
    # never-auto-repair category -> proposal-only
    assert is_apply_eligible(_finding(category="security_issue"), _proposal("GOOD"), wc) is False
    assert (
        is_apply_eligible(
            _finding(category="architecture_boundary_violation"), _proposal("GOOD"), wc
        )
        is False
    )
    # protected path -> never
    assert is_apply_eligible(_finding(protected_path=True), _proposal("GOOD"), wc) is False
    # over write ceiling -> never
    assert is_apply_eligible(_finding(tier_impact=TierLevel.t4), _proposal("GOOD"), wc) is False


# --- apply loop ------------------------------------------------------------


def test_apply_success(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = apply_llm_proposals(
        _pr(), [(_finding(), _proposal("GOOD"))], _config(tmp_path, _CHECK_GOOD), repo
    )

    assert result is not None
    assert result.status == "completed"
    assert result.retries_used == 0
    assert result.modified_files == ["f.py"]
    assert result.applied_finding_ids == ["mr-1"]
    assert (repo / "f.py").read_text() == "GOOD\n"


def test_apply_retries_once_then_succeeds(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    # First attempt writes BROKEN (fails verification); retry writes GOOD.
    def regenerate(stderr: str):
        return [(_finding(), _proposal("GOOD"))]

    result = apply_llm_proposals(
        _pr(), [(_finding(), _proposal("BROKEN"))], _config(tmp_path, _CHECK_GOOD), repo, regenerate
    )

    assert result is not None
    assert result.status == "completed"
    assert result.retries_used == 1
    assert (repo / "f.py").read_text() == "GOOD\n"


def test_apply_both_attempts_fail_rolls_back(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    result = apply_llm_proposals(
        _pr(),
        [(_finding(), _proposal("BROKEN"))],
        _config(tmp_path, _CHECK_GOOD),
        repo,
        regenerate=lambda stderr: [(_finding(), _proposal("STILL_BROKEN"))],
    )

    assert result is not None
    assert result.status == "rolled_back_verification_failed"
    assert result.retries_used == 1
    assert result.modified_files == []
    assert (repo / "f.py").read_text() == "OLD\n"  # restored
    assert _run_porcelain(repo) == ""  # clean tree


def test_rollback_preserves_prior_autofix_changes(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # Simulate a prior, uncommitted autofix change to a different tracked file.
    (repo / "a.py").write_text("AUTOFIXED\n", encoding="utf-8")

    result = apply_llm_proposals(
        _pr(),
        [(_finding(), _proposal("BROKEN"))],
        _config(tmp_path, _CHECK_GOOD),
        repo,
    )

    assert result is not None and result.status == "rolled_back_verification_failed"
    assert (repo / "a.py").read_text() == "AUTOFIXED\n"  # autofix change preserved
    assert (repo / "f.py").read_text() == "OLD\n"  # llm change rolled back


def test_apply_rolls_back_on_exception(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    # An out-of-range range makes apply_patch_instructions raise mid-apply.
    bad = ProposedPatch(
        finding_id="mr-1",
        file_path="f.py",
        abstained=False,
        instruction={
            "op": "replace_range",
            "file_path": "f.py",
            "line_start": 50,
            "line_end": 60,
            "replacement": "x",
            "finding_id": "mr-1",
        },
    )

    with pytest.raises(ValueError):
        apply_llm_proposals(_pr(), [(_finding(), bad)], _config(tmp_path, _CHECK_GOOD), repo)

    # Rolled back like the deterministic lane: tree clean, file unchanged.
    assert (repo / "f.py").read_text() == "OLD\n"
    assert _run_porcelain(repo) == ""


def test_no_applicable_returns_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    abstained = ProposedPatch(finding_id="mr-1", abstained=True)
    assert (
        apply_llm_proposals(_pr(), [(_finding(), abstained)], _config(tmp_path, _CHECK_GOOD), repo)
        is None
    )


def _run_porcelain(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_apply_refuses_a_proposal_with_no_expected_block(tmp_path: Path) -> None:
    """Fail closed: an unguarded range replacement must not reach the file.

    This is the shape the LLM proposer used to emit -- model-chosen line
    numbers with no content to verify them against.
    """
    repo = _repo(tmp_path)
    unguarded = ProposedPatch(
        finding_id="mr-1",
        file_path="f.py",
        abstained=False,
        instruction={
            "op": "replace_range",
            "file_path": "f.py",
            "line_start": 1,
            "line_end": 1,
            "replacement": "PWNED",
            "finding_id": "mr-1",
        },
    )

    pr, finding, config = _pr(), _finding(), _config(tmp_path, _CHECK_GOOD)

    with pytest.raises(ValueError, match="requires expected_block"):
        apply_llm_proposals(pr, [(finding, unguarded)], config, repo)
    assert (repo / "f.py").read_text() == "OLD\n"


def test_apply_aborts_when_the_expected_block_is_stale(tmp_path: Path) -> None:
    """Content drift aborts instead of overwriting whatever is there now."""
    repo = _repo(tmp_path)
    stale = _proposal("NEW", expected_block=["WHAT THE MODEL THOUGHT WAS HERE"])

    pr, finding, config = _pr(), _finding(), _config(tmp_path, _CHECK_GOOD)

    with pytest.raises(ValueError, match="expected block mismatch"):
        apply_llm_proposals(pr, [(finding, stale)], config, repo)
    assert (repo / "f.py").read_text() == "OLD\n"
