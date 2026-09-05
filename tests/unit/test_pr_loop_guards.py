from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from pr_repair.config import AppConfig
from pr_repair.orchestration.pr_loop import PRLoopConfig, PRLoopOrchestrator, PRLoopState
from pr_repair.runtime.pr_state_store import PRStateStore
from pr_repair.server.github_webhook import WebhookSignatureError, parse_github_webhook
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
        allow_push=False,
        output_dir=tmp_path,
        write_ceiling=TierLevel.t1,
    )


def _pr(**overrides) -> PRRef:
    data = {
        "repo_owner": "owner",
        "repo_name": "repo",
        "pr_number": 7,
        "title": "Fix thing",
        "head_branch": "feature/fix",
        "base_branch": "main",
        "head_sha": "sha-1",
        "is_draft": False,
        "author": "dev",
        "labels": [],
    }
    data.update(overrides)
    return PRRef(**data)


def _finding(**overrides) -> Finding:
    data = {
        "finding_id": "f-1",
        "pr_number": 7,
        "source_name": SourceName.agent_review,
        "source_priority": 100,
        "severity": Severity.medium,
        "category": "lint_failure",
        "message": "bad line",
        "file_path": "src/example.py",
        "line_start": 1,
        "line_end": 1,
        "suggested_fix": "good line",
        "repairable": True,
        "confidence": 0.95,
        "fingerprint": "fp-1",
        "tier_impact": TierLevel.t1,
        "protected_path": False,
        "skip_review_path": False,
        "classification_reason": "test",
    }
    data.update(overrides)
    return Finding(**data)


def _execution(plan, config, repo_root):
    return RepairExecution(
        execution_id="exec-1",
        pr_ref=plan.pr_ref,
        plan_id=plan.plan_id,
        mode=plan.execution_mode,
        modified_files=["src/example.py"],
        push_result="commit-sha",
        status="completed",
    )


def test_max_attempts_stops_loop(tmp_path) -> None:
    store = PRStateStore(tmp_path / "state")
    pr = _pr()
    state = store.get_or_create(
        repo_full_name=pr.repo_full_name,
        pr_number=pr.pr_number,
        head_sha=pr.head_sha,
        head_branch=pr.head_branch,
        base_branch=pr.base_branch,
    )
    state.attempt = 3
    store.save(state)
    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=store,
        finding_provider=lambda _pr: [_finding()],
        signal_provider=lambda _pr: ("failure", "approved"),
        loop_config=PRLoopConfig(max_repair_attempts=3),
        repair_executor=_execution,
    )

    result = loop.on_signals_completed(pr)

    assert result.state is PRLoopState.max_attempts_reached
    assert result.persisted_state.terminal_state is True
    assert result.persisted_state.terminal_reason == "max_attempts_reached"


def test_repeated_same_failure_stops_loop(tmp_path) -> None:
    store = PRStateStore(tmp_path / "state")
    pr = _pr()
    finding = _finding()
    first_loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=store,
        finding_provider=lambda _pr: [finding],
        signal_provider=lambda _pr: ("failure", "approved"),
        repair_executor=_execution,
    )
    first = first_loop.on_signals_completed(pr)
    assert first.state is PRLoopState.waiting_for_ci_rerun

    second = first_loop.on_signals_completed(pr)

    assert second.state is PRLoopState.blocked
    assert second.persisted_state.terminal_reason == "repeated_same_failure"


def test_protected_path_requires_approval(tmp_path) -> None:
    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=PRStateStore(tmp_path / "state"),
        finding_provider=lambda _pr: [
            _finding(
                category="security_policy",
                file_path=".github/workflows/ci.yml",
                protected_path=True,
                tier_impact=TierLevel.t5,
                severity=Severity.high,
            )
        ],
        signal_provider=lambda _pr: ("failure", "approved"),
        repair_executor=_execution,
    )

    result = loop.on_signals_completed(_pr())

    assert result.state is PRLoopState.approval_required
    assert result.persisted_state.terminal_reason == "approval_gate_denied"


def test_fork_pr_is_blocked(tmp_path) -> None:
    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=PRStateStore(tmp_path / "state"),
        finding_provider=lambda _pr: [_finding()],
    )

    result = loop.on_pr_event(_pr(), head_repo_full_name="someone/repo")

    assert result.state is PRLoopState.blocked
    assert result.persisted_state.terminal_reason == "fork_pr_detected"


def test_approval_denied_prevents_commit(tmp_path) -> None:
    called = {"value": False}

    def executor(plan, config, repo_root):
        called["value"] = True
        return _execution(plan, config, repo_root)

    loop = PRLoopOrchestrator(
        app_config=_config(tmp_path),
        state_store=PRStateStore(tmp_path / "state"),
        finding_provider=lambda _pr: [_finding(protected_path=True, tier_impact=TierLevel.t5)],
        signal_provider=lambda _pr: ("failure", "approved"),
        repair_executor=executor,
    )

    result = loop.on_signals_completed(_pr())

    assert result.state is PRLoopState.approval_required
    assert called["value"] is False


def test_invalid_webhook_signature_rejected() -> None:
    body = b'{"action":"opened"}'
    with pytest.raises(WebhookSignatureError):
        parse_github_webhook(
            raw_body=body,
            headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=bad"},
            secret="secret",
        )


def test_unsupported_event_ignored_safely() -> None:
    payload = {"action": "closed", "repository": {"full_name": "owner/repo"}}
    body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()

    event = parse_github_webhook(
        raw_body=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig},
        secret="secret",
    )

    assert event.trigger == "ignored"
    assert event.supported is False
