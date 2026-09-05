from pr_repair.priorities import SEVERITY_PRIORITY, SOURCE_PRIORITY
from pr_repair.types import Severity, SourceName


def test_source_priority_contract_is_correct() -> None:
    # The deterministic agent_review payload is the highest-authority source.
    assert SOURCE_PRIORITY[SourceName.agent_review] > SOURCE_PRIORITY[SourceName.github_checks]
    assert (
        SOURCE_PRIORITY[SourceName.github_checks]
        > SOURCE_PRIORITY[SourceName.github_review_comments]
    )
    assert (
        SOURCE_PRIORITY[SourceName.github_review_comments]
        > SOURCE_PRIORITY[SourceName.github_issue_comments]
    )


def test_severity_priority_contract_is_correct() -> None:
    assert SEVERITY_PRIORITY[Severity.critical] > SEVERITY_PRIORITY[Severity.high]
    assert SEVERITY_PRIORITY[Severity.high] > SEVERITY_PRIORITY[Severity.medium]
    assert SEVERITY_PRIORITY[Severity.medium] > SEVERITY_PRIORITY[Severity.low]
