from pr_repair.priorities import SOURCE_PRIORITY
from pr_repair.types import SourceName


def test_comment_priority_never_exceeds_tool_priority() -> None:
    assert (
        SOURCE_PRIORITY[SourceName.github_review_comments]
        < SOURCE_PRIORITY[SourceName.github_checks]
    )
    assert (
        SOURCE_PRIORITY[SourceName.github_issue_comments]
        < SOURCE_PRIORITY[SourceName.github_checks]
    )
    assert (
        SOURCE_PRIORITY[SourceName.github_review_comments]
        < SOURCE_PRIORITY[SourceName.agent_review]
    )
    assert (
        SOURCE_PRIORITY[SourceName.github_issue_comments] < SOURCE_PRIORITY[SourceName.agent_review]
    )
