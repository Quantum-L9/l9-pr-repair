from pathlib import Path

from pr_repair.repair.patch_generator import generate_patch_instructions
from pr_repair.types import (
    ExecutionMode,
    Finding,
    PRRef,
    RepairPlan,
    Severity,
    SourceName,
    TierLevel,
)


def test_generate_patch_instructions_reads_live_file_content(tmp_path: Path) -> None:
    file_path = tmp_path / "script.py"
    file_path.write_text("line1\nactual line\nline3\n", encoding="utf-8")

    pr = PRRef(
        repo_owner="owner",
        repo_name="repo",
        pr_number=1,
        title="fix",
        head_branch="fix",
        base_branch="main",
        head_sha="sha",
        is_draft=False,
        author="dev",
        labels=[],
    )
    plan = RepairPlan(
        plan_id="plan",
        pr_ref=pr,
        targeted_findings=[
            Finding(
                finding_id="f-1",
                pr_number=1,
                source_name=SourceName.agent_review,
                source_priority=100,
                severity=Severity.medium,
                category="lint_failure",
                message="Unused import detected.",
                file_path="script.py",
                line_start=2,
                line_end=2,
                suggested_fix="new line",
                repairable=True,
                confidence=0.9,
                fingerprint="fp-1",
                tier_impact=TierLevel.t1,
            )
        ],
        target_files=["script.py"],
        target_tier=TierLevel.t1,
        protected_paths_touched=False,
        verification_command=["python", "-c", "print('ok')"],
        risk_level="low",
        approval_required=False,
        executable=True,
        execution_mode=ExecutionMode.repair_and_verify,
        rationale="safe",
    )

    instructions = generate_patch_instructions(plan, tmp_path)

    assert instructions == [
        {
            "op": "replace_line",
            "file_path": "script.py",
            "line_number": 2,
            "expected": "actual line",
            "replacement": "new line",
            "finding_id": "f-1",
            "category": "lint_failure",
        }
    ]
