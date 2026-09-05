# --- L9_META ---
# l9_schema: 1
# origin: pr_repair_pipeline
# engine: pr_repair
# layer: [repair]
# tags: [llm, apply, verify, rollback, retry]
# owner: platform
# status: active
# --- /L9_META ---

"""Closed-loop application of LLM-assisted repair proposals.

Runs actionable ``ProposedPatch`` instructions through the same exact-match
applier + native verification + rollback rails as the deterministic lane, with a
single retry that feeds the verification stderr back to the router. Gated behind
``config.llm_apply`` and governance: protected paths, never-auto-repair
categories (security/contract/architecture/protected), and findings above the
write ceiling are never auto-applied -- they stay proposal-only. Native
verification is the hard gate; the bot proposes, and only commits what passes.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from pathlib import Path

from pr_repair.classification.classifier import is_never_auto_repair
from pr_repair.config import AppConfig
from pr_repair.llm.contract import ProposedPatch
from pr_repair.logging import log_event
from pr_repair.priorities import is_within_write_ceiling
from pr_repair.repair.patch_applier import apply_patch_instructions
from pr_repair.types import (
    ExecutionMode,
    Finding,
    PRRef,
    RepairExecution,
    TierLevel,
    VerificationReport,
)
from pr_repair.verification.native_runner import run_verification
from pr_repair.workspace.git_ops import (
    checkout_pr_branch,
    commit_changes,
    push_changes,
    restore_worktree,
    snapshot_worktree,
)

MAX_RETRIES = 1

# Proposal pair: the finding and the model's structured patch for it.
Proposal = tuple[Finding, ProposedPatch]
Regenerate = Callable[[str], list[Proposal]]


def is_apply_eligible(finding: Finding, proposal: ProposedPatch, write_ceiling: TierLevel) -> bool:
    """Governance gate: which proposals may be auto-applied at all."""
    if proposal.abstained or proposal.instruction is None:
        return False
    if finding.protected_path:
        return False
    if is_never_auto_repair(finding.category):
        return False
    return is_within_write_ceiling(finding.tier_impact, write_ceiling)


def apply_llm_proposals(
    pr_ref: PRRef,
    applicable: list[Proposal],
    config: AppConfig,
    repo_root: Path,
    regenerate: Regenerate | None = None,
) -> RepairExecution | None:
    """Apply eligible LLM proposals with native verification and a single retry.

    Returns None when there is nothing to apply. On verification failure the
    working tree is restored to its pre-apply snapshot (preserving any prior
    autofix changes); one retry is attempted with the stderr fed back to the
    router before giving up.
    """
    instructions = _instructions(applicable)
    if not instructions:
        return None

    checkout_pr_branch(pr_ref, repo_root)
    snapshot = snapshot_worktree(repo_root)
    attempt = 0

    try:
        while True:
            applied = apply_patch_instructions(instructions, repo_root)
            modified = applied.modified_files
            applied_finding_ids = applied.applied_finding_ids
            log_event(
                "llm_patch_applied",
                pr_number=pr_ref.pr_number,
                attempt=attempt,
                modified_files=modified,
                applied_finding_ids=applied_finding_ids,
            )
            verification = run_verification(config.verify_command, repo_root)
            log_event(
                "llm_verification_complete",
                pr_number=pr_ref.pr_number,
                attempt=attempt,
                success=verification.success,
                exit_code=verification.exit_code,
            )

            if verification.success:
                push_result = None
                if config.allow_push and config.mode is ExecutionMode.repair_verify_and_push:
                    commit_sha = commit_changes(
                        f"fix(pr-{pr_ref.pr_number}): apply LLM-assisted repair (verified)",
                        repo_root,
                    )
                    push_changes(pr_ref.head_branch, repo_root)
                    push_result = f"pushed:{commit_sha}"
                return _execution(
                    pr_ref,
                    config,
                    "completed",
                    modified,
                    applied_finding_ids,
                    verification,
                    attempt,
                    push_result,
                )

            restore_worktree(snapshot, repo_root)
            log_event("llm_repair_rolled_back", pr_number=pr_ref.pr_number, attempt=attempt)

            if attempt >= MAX_RETRIES or regenerate is None:
                return _execution(
                    pr_ref,
                    config,
                    "rolled_back_verification_failed",
                    [],
                    [],
                    verification,
                    attempt,
                    None,
                )

            attempt += 1
            instructions = _instructions(regenerate(verification.stderr))
            if not instructions:
                return _execution(
                    pr_ref,
                    config,
                    "rolled_back_no_retry_patch",
                    [],
                    [],
                    verification,
                    attempt,
                    None,
                )
    except BaseException:
        # A raise from apply/verify/regenerate (unsupported op, exact-match mismatch,
        # missing file, ...) must not leave the tree dirty -- roll back like the
        # deterministic lane, then surface the error.
        #
        # BaseException, not Exception: interrupting a run mid-apply is exactly
        # when a dirty worktree must not survive, and KeyboardInterrupt does not
        # derive from Exception. The block re-raises, so nothing is swallowed.
        restore_worktree(snapshot, repo_root)
        log_event(
            "llm_repair_rolled_back",
            pr_number=pr_ref.pr_number,
            attempt=attempt,
            reason="exception",
        )
        raise


def _instructions(applicable: list[Proposal]) -> list[dict[str, object]]:
    return [proposal.instruction for _, proposal in applicable if proposal.instruction is not None]


def _execution(
    pr_ref: PRRef,
    config: AppConfig,
    status: str,
    modified: list[str],
    applied_finding_ids: list[str],
    verification: VerificationReport,
    retries: int,
    push_result: str | None,
) -> RepairExecution:
    return RepairExecution(
        execution_id=str(uuid.uuid4()),
        pr_ref=pr_ref,
        plan_id=f"llm-{pr_ref.pr_number}",
        mode=config.mode,
        modified_files=modified,
        applied_finding_ids=applied_finding_ids,
        verification_result=verification,
        push_result=push_result,
        status=status,
        retries_used=retries,
    )
