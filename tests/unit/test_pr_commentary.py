from pr_repair.llm.contract import ProposedPatch
from pr_repair.output.pr_commentary import MARKER, build_pr_comment, upsert_implementer_comment
from pr_repair.types import (
    ExecutionMode,
    Finding,
    PRRef,
    RepairExecution,
    ReviewDisposition,
    Severity,
    SourceName,
    VerificationReport,
)


def _pr(pr_number: int = 61) -> PRRef:
    return PRRef(
        repo_owner="owner",
        repo_name="repo",
        pr_number=pr_number,
        title="repair",
        head_branch="fix/repair",
        base_branch="main",
        head_sha=f"sha-{pr_number}",
        is_draft=False,
        author="dev",
        labels=[],
    )


def _finding(**overrides) -> Finding:
    base = dict(
        finding_id="f-61",
        pr_number=61,
        source_name=SourceName.agent_review,
        source_priority=110,
        severity=Severity.high,
        category="architecture_boundary_violation",
        message="from fastapi import FastAPI in engine module",
        file_path="engine/module.py",
        line_start=8,
        line_end=8,
        suggested_fix="Remove FastAPI import from engine module.",
        confidence=0.9,
        fingerprint="fp-61",
        contract_ids=["C-01"],
        repo_rule_sources=["AGENT.md", "AI_AGENT_REVIEW_CHECKLIST.md"],
    )
    base.update(overrides)
    return Finding(**base)


def test_comment_carries_marker_and_table_header() -> None:
    execution = RepairExecution(
        execution_id="exec-61",
        pr_ref=_pr(),
        plan_id="plan-61",
        mode=ExecutionMode.dry_run,
        status="approval_required",
    )
    comment = build_pr_comment(
        execution, [_finding(review_disposition=ReviewDisposition.manual_review)]
    )

    assert comment.startswith(MARKER)
    assert "| Finding | Source | Patch Applied | Verification Status |" in comment
    assert "`f-61` architecture_boundary_violation" in comment


def test_comment_preserves_contract_violation_details() -> None:
    execution = RepairExecution(
        execution_id="exec-61",
        pr_ref=_pr(),
        plan_id="plan-61",
        mode=ExecutionMode.dry_run,
        status="approval_required",
    )
    comment = build_pr_comment(execution, [_finding()])

    assert "CONTRACT C-01 VIOLATION" in comment
    assert "File: engine/module.py Line: 8" in comment


def test_table_reflects_applied_autofix_and_passing_verification() -> None:
    execution = RepairExecution(
        execution_id="exec-7",
        pr_ref=_pr(7),
        plan_id="plan-7",
        mode=ExecutionMode.repair_and_verify,
        status="completed",
        modified_files=["engine/module.py"],
        applied_finding_ids=["f-61"],
        verification_result=VerificationReport(
            command=["pytest"], success=True, exit_code=0, stdout="", stderr=""
        ),
    )
    finding = _finding(
        pr_number=7,
        category="lint_failure",
        contract_ids=[],
        review_disposition=ReviewDisposition.autofix,
    )
    comment = build_pr_comment(execution, [finding])

    assert "✅ applied" in comment
    assert "✅ passing" in comment


def test_same_file_second_finding_is_not_marked_applied() -> None:
    execution = RepairExecution(
        execution_id="exec-7",
        pr_ref=_pr(7),
        plan_id="plan-7",
        mode=ExecutionMode.repair_and_verify,
        status="completed",
        modified_files=["engine/module.py"],
        applied_finding_ids=["f-61"],
        verification_result=VerificationReport(
            command=["pytest"], success=True, exit_code=0, stdout="", stderr=""
        ),
    )
    applied = _finding(
        pr_number=7,
        category="lint_failure",
        contract_ids=[],
        review_disposition=ReviewDisposition.autofix,
    )
    other = _finding(
        finding_id="f-62",
        pr_number=7,
        category="lint_failure",
        contract_ids=[],
        fingerprint="fp-62",
        review_disposition=ReviewDisposition.autofix,
    )
    comment = build_pr_comment(execution, [applied, other])

    assert "`f-61`" in comment
    assert "`f-62`" in comment
    rows = [line for line in comment.splitlines() if line.startswith("| `")]
    assert any("✅ applied" in row and "`f-61`" in row for row in rows)
    assert any("—" in row and "`f-62`" in row for row in rows)


def test_table_reflects_manual_proposal() -> None:
    execution = RepairExecution(
        execution_id="exec-9",
        pr_ref=_pr(9),
        plan_id="plan-9",
        mode=ExecutionMode.dry_run,
        status="planned_only",
    )
    finding = _finding(
        pr_number=9, contract_ids=[], review_disposition=ReviewDisposition.manual_review
    )
    proposal = ProposedPatch(finding_id="f-61", file_path="engine/module.py", abstained=False)
    comment = build_pr_comment(execution, [finding], [proposal])

    assert "📝 proposed" in comment


class _FakeConnector:
    def __init__(self, existing):
        self._existing = existing
        self.posted = []
        self.updated = []
        self.deleted = []

    def get_issue_comments(self, owner, repo, pr_number):
        return self._existing

    def post_pr_comment(self, owner, repo, pr_number, body):
        self.posted.append(body)
        return {"id": 999, "body": body}

    def update_issue_comment(self, owner, repo, comment_id, body):
        self.updated.append((comment_id, body))
        return {"id": comment_id, "body": body}

    def delete_issue_comment(self, owner, repo, comment_id):
        self.deleted.append(comment_id)


def test_upsert_creates_when_no_marker_present() -> None:
    connector = _FakeConnector(existing=[{"id": 1, "body": "unrelated human comment"}])
    body = f"{MARKER}\nbody"
    upsert_implementer_comment(connector, _pr(), body)

    assert connector.posted == [body]
    assert connector.updated == []


def test_upsert_updates_existing_marked_comment() -> None:
    connector = _FakeConnector(
        existing=[
            {"id": 1, "body": "human comment"},
            {"id": 42, "body": f"{MARKER}\nold table"},
        ]
    )
    body = f"{MARKER}\nnew table"
    upsert_implementer_comment(connector, _pr(), body)

    assert connector.updated == [(42, body)]
    assert connector.posted == []


def test_upsert_deletes_duplicate_marker_comments() -> None:
    connector = _FakeConnector(
        existing=[
            {"id": 10, "body": f"{MARKER}\nfirst"},
            {"id": 1, "body": "human comment"},
            {"id": 20, "body": f"{MARKER}\nolder duplicate"},
        ]
    )
    body = f"{MARKER}\nnew table"
    upsert_implementer_comment(connector, _pr(), body)

    # First marker comment updated, the duplicate deleted -> exactly one remains.
    assert connector.updated == [(10, body)]
    assert connector.deleted == [20]
    assert connector.posted == []


def test_upsert_requires_marker_at_start() -> None:
    connector = _FakeConnector(existing=[])
    try:
        upsert_implementer_comment(connector, _pr(), f"prefix text\n{MARKER}\nbody")
    except ValueError as exc:
        assert "start with" in str(exc)
    else:
        raise AssertionError("expected ValueError for non-leading marker")


def test_upsert_ignores_comment_that_merely_quotes_marker() -> None:
    # A human comment that quotes the marker mid-body must not be mistaken for the
    # bot's comment; a fresh comment is created instead of overwriting it.
    connector = _FakeConnector(existing=[{"id": 7, "body": f"quoting the bot: `{MARKER}`"}])
    body = f"{MARKER}\ntable"
    upsert_implementer_comment(connector, _pr(), body)

    assert connector.posted == [body]
    assert connector.updated == []


def test_upsert_rejects_body_without_marker() -> None:
    connector = _FakeConnector(existing=[])
    try:
        upsert_implementer_comment(connector, _pr(), "no marker here")
    except ValueError as exc:
        assert "marker" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing marker")
