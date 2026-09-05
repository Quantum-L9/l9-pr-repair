from pr_repair.server.github_webhook import NormalizedPREvent
from pr_repair.tools.copilot import CopilotAdapter
from pr_repair.types import PRRef


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


def _thread(
    body: str, *, resolved: bool = False, login: str = "copilot-pull-request-reviewer[bot]"
) -> dict:
    return {
        "id": "PRRT_1",
        "isResolved": resolved,
        "path": "engine.py",
        "line": 2,
        "comments": {
            "nodes": [
                {
                    "id": "PRRC_1",
                    "databaseId": 5001,
                    "body": body,
                    "author": {"login": login},
                    "url": "https://x",
                }
            ]
        },
    }


class _Conn:
    def __init__(self, threads: list[dict]) -> None:
        self._threads = threads

    def get_review_threads(self, owner: str, repo: str, pr: int) -> list[dict]:
        return self._threads


def _event(tool: str | None) -> NormalizedPREvent:
    return NormalizedPREvent(
        "pull_request_review", "submitted", "review_completed", "owner/repo", 7, "sha", {}, tool
    )


def test_matches_only_copilot_events() -> None:
    adapter = CopilotAdapter()
    assert adapter.matches(_event("copilot")) is True
    assert adapter.matches(_event("coderabbit")) is False
    assert adapter.matches(_event(None)) is False


def test_suggestion_block_becomes_autofix() -> None:
    adapter = CopilotAdapter()
    body = "Rename it.\n```suggestion\nTransportPacket\n```"
    raw = adapter.read_findings(_pr(), _Conn([_thread(body)]))
    findings = adapter.to_payload_findings(raw)

    assert len(findings) == 1
    f = findings[0]
    assert f["_disposition"] == "autofix"
    assert f["replacement_text"] == "TransportPacket"
    assert f["file_path"] == "engine.py"
    assert f["line_start"] == 2 and f["line_end"] == 2
    assert f["tool"] == "copilot"
    assert f["thread_id"] == "PRRT_1"
    assert f["comment_id"] == 5001
    assert f["finding_id"] == "copilot-5001"


def test_plain_comment_becomes_manual_review() -> None:
    adapter = CopilotAdapter()
    raw = adapter.read_findings(
        _pr(), _Conn([_thread("This looks like an architecture boundary violation.")])
    )
    findings = adapter.to_payload_findings(raw)

    assert findings[0]["_disposition"] == "manual_review"
    assert "replacement_text" not in findings[0]
    assert findings[0]["category"] == "architecture_boundary_violation"


def test_resolved_and_non_copilot_threads_are_ignored() -> None:
    adapter = CopilotAdapter()
    threads = [
        _thread("resolved copilot", resolved=True),
        _thread("human comment", login="a-human"),
    ]
    assert adapter.read_findings(_pr(), _Conn(threads)) == []
