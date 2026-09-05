import subprocess
from pathlib import Path

from pr_repair.config import AppConfig
from pr_repair.repair.repair_executor import execute_repair_plan
from pr_repair.types import (
    ExecutionMode,
    Finding,
    PRRef,
    RepairPlan,
    Severity,
    SourceName,
    TierLevel,
)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def test_execute_repair_plan_applies_and_verifies_without_push(tmp_path: Path) -> None:
    _run(["git", "init"], tmp_path)
    _run(["git", "config", "user.email", "test@example.com"], tmp_path)
    _run(["git", "config", "user.name", "Test User"], tmp_path)
    file_path = tmp_path / "script.py"
    file_path.write_text("line1\nbad line\nline3\n", encoding="utf-8")
    _run(["git", "add", "script.py"], tmp_path)
    _run(["git", "commit", "-m", "init"], tmp_path)
    _run(["git", "checkout", "-b", "fix-branch"], tmp_path)

    config = AppConfig(
        github_token="token",
        github_repository="owner/repo",
        verify_command=["python", "-c", "print('verify')"],
        mode=ExecutionMode.repair_and_verify,
        output_dir=tmp_path / "runtime",
        write_ceiling=TierLevel.t1,
    )
    pr = PRRef(
        repo_owner="owner",
        repo_name="repo",
        pr_number=77,
        title="repair",
        head_branch="fix-branch",
        base_branch="main",
        head_sha="sha-77",
        is_draft=False,
        author="dev",
        labels=[],
    )
    plan = RepairPlan(
        plan_id="plan-77",
        pr_ref=pr,
        targeted_findings=[
            Finding(
                finding_id="f-77",
                pr_number=77,
                source_name=SourceName.agent_review,
                source_priority=100,
                severity=Severity.medium,
                category="lint_failure",
                message="bad line",
                file_path="script.py",
                line_start=2,
                line_end=2,
                suggested_fix="good line",
                repairable=True,
                confidence=0.9,
                fingerprint="fp-77",
                tier_impact=TierLevel.t1,
            )
        ],
        target_files=["script.py"],
        target_tier=TierLevel.t1,
        protected_paths_touched=False,
        verification_command=["python", "-c", "print('verify')"],
        risk_level="low",
        approval_required=False,
        executable=True,
        execution_mode=ExecutionMode.repair_and_verify,
        rationale="safe",
    )

    execution = execute_repair_plan(plan, config, tmp_path)

    assert execution.status == "completed"
    assert execution.modified_files == ["script.py"]
    assert execution.applied_finding_ids == ["f-77"]
    assert execution.verification_result is not None
    assert execution.verification_result.success is True
    assert file_path.read_text(encoding="utf-8").splitlines()[1] == "good line"
