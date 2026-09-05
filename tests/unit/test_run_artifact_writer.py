from pathlib import Path

from pr_repair.output.artifact_writer import (
    write_learning_artifacts,
    write_pr_artifacts,
    write_run_artifacts,
)
from pr_repair.state_store import StateStore
from pr_repair.types import (
    ExecutionMode,
    Finding,
    FindingBundle,
    LearningPacket,
    PRRef,
    RepairExecution,
    RepairPlan,
    Severity,
    SourceName,
    TierLevel,
)


def test_write_artifacts_uses_per_pr_paths_and_root_aggregates(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    pr = PRRef(
        repo_owner="owner",
        repo_name="repo",
        pr_number=7,
        title="repair",
        head_branch="fix",
        base_branch="main",
        head_sha="sha-7",
        is_draft=False,
        author="dev",
        labels=[],
    )
    finding = Finding(
        finding_id="f-7",
        pr_number=7,
        source_name=SourceName.github_checks,
        source_priority=80,
        severity=Severity.high,
        category="github_required_check_failure",
        message="Required check failed: ci",
        confidence=0.8,
        fingerprint="fp-7",
    )
    bundle = FindingBundle(pr_ref=pr, merged_findings=[finding])
    plan = RepairPlan(
        plan_id="plan-7",
        pr_ref=pr,
        targeted_findings=[],
        target_files=[],
        target_tier=TierLevel.t0,
        protected_paths_touched=False,
        verification_command=["make", "agent-check"],
        risk_level="low",
        approval_required=False,
        executable=False,
        execution_mode=ExecutionMode.dry_run,
        rationale="none",
    )
    execution = RepairExecution(
        execution_id="exec-7",
        pr_ref=pr,
        plan_id="plan-7",
        mode=ExecutionMode.dry_run,
        status="planned_only",
    )

    write_pr_artifacts(store, bundle, [finding], [finding], plan, execution, "comment")
    write_run_artifacts(
        store,
        [pr.model_dump(mode="json")],
        [finding],
        [plan],
        [execution],
        [],
    )
    write_learning_artifacts(
        store,
        [
            LearningPacket(
                packet_id="lp-7",
                source_prs=[7],
                repeated_failures=[],
                agent_md_recommendations=[],
                validator_recommendations=[],
                confidence=0.3,
            )
        ],
        {"write_policy": "review_only_no_direct_mutation"},
        {"write_policy": "review_only_no_direct_mutation"},
    )

    assert (tmp_path / "prs" / "pr_7" / "findings_normalized.json").exists()
    assert (tmp_path / "prs" / "pr_7" / "repair_plan.json").exists()
    assert (tmp_path / "pr_inventory.json").exists()
    assert (tmp_path / "repair_plans.yaml").exists()
    assert (tmp_path / "learning_report.md").exists()
