from pr_repair.telemetry.autofix import build_autofix_telemetry
from pr_repair.types import (
    ExecutionMode,
    Finding,
    PRRef,
    RepairExecution,
    ReviewDisposition,
    Severity,
    SourceName,
)


def _pr(n: int = 1) -> PRRef:
    return PRRef(
        repo_owner="o",
        repo_name="r",
        pr_number=n,
        title="t",
        head_branch="h",
        base_branch="main",
        head_sha="s",
        is_draft=False,
        author="a",
        labels=[],
    )


def _autofix(rule_id: str | None, file_path: str = "a.py", pr: int = 1) -> Finding:
    return Finding(
        finding_id=f"af-{rule_id}-{file_path}",
        pr_number=pr,
        source_name=SourceName.agent_review,
        source_priority=110,
        severity=Severity.medium,
        category="lint_failure",
        message="m",
        file_path=file_path,
        line_start=1,
        line_end=1,
        replacement_text="x",
        rule_id=rule_id,
        review_disposition=ReviewDisposition.autofix,
        repairable=True,
        fingerprint=f"fp-{rule_id}-{file_path}",
    )


def _execution(
    status: str,
    *,
    modified=None,
    applied=None,
    false_positive=None,
    pr: int = 1,
) -> RepairExecution:
    return RepairExecution(
        execution_id="e",
        pr_ref=_pr(pr),
        plan_id="p",
        mode=ExecutionMode.repair_and_verify,
        modified_files=modified or [],
        applied_finding_ids=applied or [],
        false_positive_rules=false_positive or [],
        status=status,
    )


def test_clean_autofix_is_promotable() -> None:
    findings = [_autofix("rule-a", "a.py")]
    execs = [_execution("completed", modified=["a.py"], applied=["af-rule-a-a.py"])]

    tel = build_autofix_telemetry(findings, execs)

    rule = tel["rules"][0]
    assert rule["rule_id"] == "rule-a"
    assert rule["attempted"] == 1 and rule["verified"] == 1 and rule["applied"] == 1
    assert rule["success_rate"] == 1.0 and rule["promotable"] is True
    assert tel["promotion_candidates"] == ["rule-a"]
    assert tel["false_positive_rules"] == []
    assert tel["totals"]["verified"] == 1


def test_failed_autofix_is_false_positive_not_promotable() -> None:
    findings = [_autofix("rule-b", "a.py")]
    execs = [_execution("rolled_back_verification_failed", false_positive=["rule-b"])]

    tel = build_autofix_telemetry(findings, execs)

    rule = tel["rules"][0]
    assert rule["false_positive"] == 1 and rule["rolled_back"] == 1
    assert rule["verified"] == 0 and rule["promotable"] is False
    assert tel["promotion_candidates"] == []
    assert tel["false_positive_rules"] == ["rule-b"]


def test_no_execution_counts_attempt_only() -> None:
    tel = build_autofix_telemetry([_autofix("rule-c")], [])
    rule = tel["rules"][0]
    assert rule["attempted"] == 1 and rule["verified"] == 0 and rule["promotable"] is False


def test_findings_without_rule_id_are_skipped() -> None:
    tel = build_autofix_telemetry([_autofix(None)], [_execution("completed", modified=["a.py"])])
    assert tel["rules"] == []


def test_same_rule_aggregates_across_files() -> None:
    findings = [_autofix("rule-d", "a.py"), _autofix("rule-d", "b.py")]
    execs = [
        _execution("completed", modified=["a.py"], applied=["af-rule-d-a.py"])
    ]  # only a.py applied

    tel = build_autofix_telemetry(findings, execs)

    rule = tel["rules"][0]
    assert rule["attempted"] == 2 and rule["verified"] == 1
    assert rule["success_rate"] == 0.5 and rule["promotable"] is False
