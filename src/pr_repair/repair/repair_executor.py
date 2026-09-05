# --- L9_META ---
# l9_schema: 1
# origin: pr_repair_pipeline
# engine: pr_repair
# layer: [repair]
# tags: [execute, verify, rollback]
# owner: platform
# status: active
# --- /L9_META ---

from __future__ import annotations

import uuid
from pathlib import Path

from pr_repair.config import AppConfig
from pr_repair.logging import log_event
from pr_repair.planning.approval_gate import requires_human_approval
from pr_repair.repair.patch_applier import apply_patch_instructions
from pr_repair.repair.patch_generator import generate_patch_instructions
from pr_repair.types import ExecutionMode, RepairExecution, RepairPlan, ReviewDisposition
from pr_repair.verification.native_runner import run_verification
from pr_repair.workspace.git_ops import (
    checkout_pr_branch,
    commit_changes,
    create_backup_ref,
    push_changes,
    rollback_to_backup,
)
from pr_repair.workspace.worktree import ensure_clean_worktree


def execute_repair_plan(
    plan: RepairPlan,
    config: AppConfig,
    repo_root: Path | None = None,
) -> RepairExecution:
    root = repo_root or Path.cwd()
    if requires_human_approval(plan, config):
        return RepairExecution(
            execution_id=str(uuid.uuid4()),
            pr_ref=plan.pr_ref,
            plan_id=plan.plan_id,
            mode=plan.execution_mode,
            status="approval_required",
        )

    ensure_clean_worktree(root)
    checkout_pr_branch(plan.pr_ref, root)
    backup_ref = create_backup_ref(plan.pr_ref, root)

    try:
        instructions = generate_patch_instructions(plan, root)
        if not instructions:
            return RepairExecution(
                execution_id=str(uuid.uuid4()),
                pr_ref=plan.pr_ref,
                plan_id=plan.plan_id,
                mode=plan.execution_mode,
                status="no_applicable_instructions",
            )

        applied = apply_patch_instructions(instructions, root)
        modified_files = applied.modified_files
        applied_finding_ids = applied.applied_finding_ids
        log_event(
            "patch_applied",
            pr_number=plan.pr_ref.pr_number,
            instructions=len(instructions),
            modified_files=modified_files,
            applied_finding_ids=applied_finding_ids,
        )
        verification_result = run_verification(plan.verification_command, root)
        log_event(
            "verification_complete",
            pr_number=plan.pr_ref.pr_number,
            success=verification_result.success,
            exit_code=verification_result.exit_code,
        )
        if not verification_result.success:
            rollback_to_backup(backup_ref, root)
            log_event(
                "repair_rolled_back", pr_number=plan.pr_ref.pr_number, reason="verification_failed"
            )
            # Deterministic autofixes must never break verification. If they do,
            # the Semgrep rule is a false-positive candidate: flag it for the CI
            # platform and fail immediately -- no LLM, no retry.
            false_positive_rules = _autofix_rule_ids(plan)
            if false_positive_rules:
                log_event(
                    "autofix_false_positive_detected",
                    pr_number=plan.pr_ref.pr_number,
                    rules=false_positive_rules,
                    exit_code=verification_result.exit_code,
                )
            return RepairExecution(
                execution_id=str(uuid.uuid4()),
                pr_ref=plan.pr_ref,
                plan_id=plan.plan_id,
                mode=plan.execution_mode,
                modified_files=[],
                verification_result=verification_result,
                status="rolled_back_verification_failed",
                false_positive_rules=false_positive_rules,
            )

        push_result = None
        if config.allow_push and plan.execution_mode is ExecutionMode.repair_verify_and_push:
            commit_sha = commit_changes(
                f"fix(pr-{plan.pr_ref.pr_number}): apply deterministic repair instructions",
                root,
            )
            push_changes(plan.pr_ref.head_branch, root)
            push_result = f"pushed:{commit_sha}"

        return RepairExecution(
            execution_id=str(uuid.uuid4()),
            pr_ref=plan.pr_ref,
            plan_id=plan.plan_id,
            mode=plan.execution_mode,
            modified_files=modified_files,
            applied_finding_ids=applied_finding_ids,
            verification_result=verification_result,
            push_result=push_result,
            status="completed",
        )
    except BaseException:
        # BaseException, not Exception: this rolls the worktree back to
        # backup_ref and re-raises. Interrupting a repair is precisely when the
        # rollback must still run, and KeyboardInterrupt is not an Exception.
        rollback_to_backup(backup_ref, root)
        log_event("repair_rolled_back", pr_number=plan.pr_ref.pr_number, reason="exception")
        raise


def _autofix_rule_ids(plan: RepairPlan) -> list[str]:
    """Collect the Semgrep rule ids of deterministic autofix findings in a plan."""
    return [
        finding.rule_id
        for finding in plan.targeted_findings
        if finding.review_disposition is ReviewDisposition.autofix and finding.rule_id
    ]
