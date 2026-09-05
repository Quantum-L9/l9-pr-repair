from pr_repair.server.github_webhook import NormalizedPREvent
from pr_repair.tools.copilot import CopilotAdapter
from pr_repair.tools.registry import adapter_for_event, adapter_for_tool
from pr_repair.tools.responder import ToolThreadResponder
from pr_repair.types import Finding, PRRef, ReviewDisposition, Severity, SourceName


def _event(tool: str | None) -> NormalizedPREvent:
    return NormalizedPREvent(
        "pull_request_review", "submitted", "review_completed", "owner/repo", 7, "sha", {}, tool
    )


def test_registry_routes_copilot_and_rejects_unknown() -> None:
    assert isinstance(adapter_for_event(_event("copilot")), CopilotAdapter)
    assert adapter_for_event(_event("sonarcloud")) is not None  # registered in Phase 4
    assert adapter_for_event(_event("nonesuch")) is None  # unknown tool
    assert adapter_for_event(_event(None)) is None
    assert adapter_for_tool("copilot") is not None


def _pr() -> PRRef:
    return PRRef(
        repo_owner="owner",
        repo_name="repo",
        pr_number=7,
        title="t",
        head_branch="fix",
        base_branch="main",
        head_sha="sha",
        is_draft=False,
        author="dev",
        labels=[],
    )


def _finding() -> Finding:
    return Finding(
        finding_id="copilot-1",
        pr_number=7,
        source_name=SourceName.agent_review,
        source_priority=110,
        severity=Severity.medium,
        category="review_comment",
        message="m",
        tool="copilot",
        thread_id="PRRT_1",
        comment_id=5001,
        review_disposition=ReviewDisposition.manual_review,
        fingerprint="fp",
    )


class _FakeConn:
    def __init__(self) -> None:
        self.replies: list[tuple] = []
        self.resolved: list[str] = []

    def reply_to_review_comment(self, owner, repo, pr, comment_id, body):
        self.replies.append((owner, repo, pr, comment_id, body))
        return {"id": 1}

    def resolve_review_thread(self, thread_id):
        self.resolved.append(thread_id)
        return {"id": thread_id, "isResolved": True}


def test_fixed_outcome_replies_and_resolves() -> None:
    conn = _FakeConn()
    responder = ToolThreadResponder(conn, post_comment=True)

    result = responder.respond(_pr(), _finding(), "fixed", commit_sha="abc123")

    assert result.replied and result.resolved
    assert conn.replies[0][3] == 5001
    assert "Fixed" in conn.replies[0][4] and "abc123" in conn.replies[0][4]
    assert conn.resolved == ["PRRT_1"]


def test_justified_skip_replies_but_does_not_resolve() -> None:
    conn = _FakeConn()
    responder = ToolThreadResponder(conn, post_comment=True)

    result = responder.respond(_pr(), _finding(), "justified_skip", detail="needs human")

    assert result.replied and not result.resolved
    assert conn.resolved == []
    assert "not auto-applied" in conn.replies[0][4].lower()


def test_post_comment_gate_suppresses_all_writes() -> None:
    conn = _FakeConn()
    responder = ToolThreadResponder(conn, post_comment=False)

    result = responder.respond(_pr(), _finding(), "fixed", commit_sha="abc")

    assert not result.replied and not result.resolved
    assert conn.replies == [] and conn.resolved == []
