from __future__ import annotations

from pr_repair.config import AppConfig
from pr_repair.orchestration.pr_loop import PRLoopConfig, PRLoopOrchestrator, PRLoopState
from pr_repair.runtime.pr_state_store import PRStateStore
from pr_repair.types import (
    ExecutionMode,
    Finding,
    PRRef,
    RepairExecution,
    Severity,
    SourceName,
    TierLevel,
)


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        github_token="token",
        github_repository="owner/repo",
        verify_command=["python", "-m", "pytest"],
        mode=ExecutionMode.dry_run,
        output_dir=tmp_path,
        write_ceiling=TierLevel.t1,
    )


def _pr(sha: str = "sha-1") -> PRRef:
    return PRRef(
        repo_owner="owner",
        repo_name="repo",
        pr_number=12,
        title="Fix CI",
        head_branch="fix/ci",
        base_branch="main",
        head_sha=sha,
        is_draft=False,
        author="dev",
        labels=[],
    )


def _finding(fp: str = "fp-1") -> Finding:
    return Finding(
        finding_id="f-1",
        pr_number=12,
        source_name=SourceName.agent_review,
        source_priority=100,
        severity=Severity.medium,
        category="lint_failure",
        message="bad line",
        file_path="src/example.py",
        line_start=1,
        line_end=1,
        suggested_fix="good line",
        repairable=True,
        confidence=0.95,
        fingerprint=fp,
        tier_impact=TierLevel.t1,
        protected_path=False,
        skip_review_path=False,
        classification_reason="test",
    )


def test_pr_opened_triggers_waiting_state(tmp_path) -> None:
    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=PRStateStore(tmp_path / "state"),
        finding_provider=lambda _pr: [],
        signal_provider=lambda _pr: ("pending", "pending"),
    )

    result = loop.on_pr_event(_pr())

    assert result.state is PRLoopState.waiting_for_signals
    assert result.persisted_state.ci_status == "pending"


def test_failed_ci_triggers_repair_planning(tmp_path) -> None:
    captured = {"called": False}

    def executor(plan, config, repo_root):
        captured["called"] = True
        return RepairExecution(
            execution_id="exec-1",
            pr_ref=plan.pr_ref,
            plan_id=plan.plan_id,
            mode=plan.execution_mode,
            modified_files=["src/example.py"],
            push_result="commit-sha",
            status="completed",
        )

    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=PRStateStore(tmp_path / "state"),
        finding_provider=lambda _pr: [_finding()],
        signal_provider=lambda _pr: ("failure", "approved"),
        repair_executor=executor,
    )

    result = loop.on_signals_completed(_pr())

    assert captured["called"] is True
    assert result.plan is not None
    assert result.state is PRLoopState.waiting_for_ci_rerun


def test_approved_bounded_patch_commits_to_pr_branch(tmp_path) -> None:
    def executor(plan, config, repo_root):
        return RepairExecution(
            execution_id="exec-2",
            pr_ref=plan.pr_ref,
            plan_id=plan.plan_id,
            mode=plan.execution_mode,
            modified_files=["src/example.py"],
            push_result="pushed:commit-sha",
            status="completed",
        )

    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=PRStateStore(tmp_path / "state"),
        finding_provider=lambda _pr: [_finding()],
        signal_provider=lambda _pr: ("failure", "approved"),
        repair_executor=executor,
    )

    result = loop.on_signals_completed(_pr())

    assert result.state is PRLoopState.waiting_for_ci_rerun
    assert result.persisted_state.last_repair_commit == "pushed:commit-sha"


def test_ci_rerun_returns_clean_and_stops(tmp_path) -> None:
    store = PRStateStore(tmp_path / "state")
    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=store,
        finding_provider=lambda _pr: [],
        signal_provider=lambda _pr: ("success", "approved"),
    )

    result = loop.on_signals_completed(_pr("sha-2"))

    assert result.state is PRLoopState.clean
    assert result.persisted_state.terminal_state is True
    assert result.persisted_state.terminal_reason == "clean"


def test_max_repair_attempts_terminally_blocks(tmp_path) -> None:
    def executor(plan, config, repo_root):
        return RepairExecution(
            execution_id="exec-3",
            pr_ref=plan.pr_ref,
            plan_id=plan.plan_id,
            mode=plan.execution_mode,
            status="rolled_back_verification_failed",
        )

    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=PRStateStore(tmp_path / "state"),
        finding_provider=lambda _pr: [_finding(fp="fp-changing")],
        signal_provider=lambda _pr: ("failure", "approved"),
        repair_executor=executor,
        loop_config=PRLoopConfig(max_repair_attempts=1),
    )

    result = loop.on_signals_completed(_pr())

    assert result.state is PRLoopState.max_attempts_reached
    assert result.persisted_state.terminal_reason == "failed_tests_after_max_attempts"
