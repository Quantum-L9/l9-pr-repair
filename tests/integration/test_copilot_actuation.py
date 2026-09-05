import json
from pathlib import Path

from pr_repair.config import AppConfig
from pr_repair.orchestration import tool_dispatcher
from pr_repair.orchestration.tool_dispatcher import run_tool_actuation
from pr_repair.tools.copilot import CopilotAdapter
from pr_repair.types import ExecutionMode, PRRef, RepairExecution, TierLevel


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


def _thread(body: str, thread_id: str, comment_id: int) -> dict:
    return {
        "id": thread_id,
        "isResolved": False,
        "path": "engine.py",
        "line": 2,
        "comments": {
            "nodes": [
                {
                    "id": "PRRC",
                    "databaseId": comment_id,
                    "body": body,
                    "author": {"login": "copilot-pull-request-reviewer[bot]"},
                    "url": "https://x",
                }
            ]
        },
    }


class _FakeConn:
    def __init__(self, threads: list[dict]) -> None:
        self._threads = threads
        self.replies: list[tuple] = []
        self.resolved: list[str] = []

    def get_review_threads(self, owner, repo, pr):
        return self._threads

    def reply_to_review_comment(self, owner, repo, pr, comment_id, body):
        self.replies.append((comment_id, body))
        return {"id": 1}

    def resolve_review_thread(self, thread_id):
        self.resolved.append(thread_id)
        return {"id": thread_id, "isResolved": True}


def _config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        github_token="t",
        github_repository="owner/repo",
        mode=ExecutionMode.repair_and_verify,
        post_comment=True,
        output_dir=tmp_path / "runtime",
        write_ceiling=TierLevel.t1,
    )


def test_copilot_suggestion_is_fixed_replied_and_resolved(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("# AGENT\n", encoding="utf-8")
    (tmp_path / "engine.py").write_text("a\nPacketEnvelope\nc\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    body = "Rename it.\n```suggestion\nTransportPacket\n```"
    conn = _FakeConn([_thread(body, "PRRT_fix", 5001)])

    # Simulate the deterministic executor applying the suggestion + verifying.
    def fake_execute(plan, cfg, repo_root=None):
        (tmp_path / "engine.py").write_text("a\nTransportPacket\nc\n", encoding="utf-8")
        return RepairExecution(
            execution_id="e",
            pr_ref=plan.pr_ref,
            plan_id=plan.plan_id,
            mode=plan.execution_mode,
            status="completed",
            modified_files=["engine.py"],
            applied_finding_ids=[finding.finding_id for finding in plan.targeted_findings],
            push_result="pushed:abc123",
        )

    monkeypatch.setattr(tool_dispatcher, "execute_repair_plan", fake_execute)

    result = run_tool_actuation(CopilotAdapter(), _pr(), _config(tmp_path), conn, tmp_path)

    assert result.autofix == 1 and result.manual == 0
    assert (tmp_path / "engine.py").read_text(encoding="utf-8") == "a\nTransportPacket\nc\n"
    assert conn.replies[0][0] == 5001
    assert "Fixed" in conn.replies[0][1] and "abc123" in conn.replies[0][1]
    assert conn.resolved == ["PRRT_fix"]

    # Phase 5: per-fix audit artifact.
    report = json.loads(
        (tmp_path / "runtime" / "prs" / "pr_7" / "fixes" / "copilot-5001.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["outcome"] == "fixed"
    assert report["commit_sha"] == "abc123"
    assert report["change"]["replacement_text"] == "TransportPacket"
    assert report["thread"]["resolved"] is True


def test_plain_copilot_comment_is_justified_not_resolved(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / "AGENT.md").write_text("# AGENT\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    conn = _FakeConn(
        [_thread("Consider refactoring this architecture boundary.", "PRRT_manual", 6002)]
    )

    # Default NullLLMClient abstains -> no proposal -> justified skip.
    result = run_tool_actuation(CopilotAdapter(), _pr(), _config(tmp_path), conn, tmp_path)

    assert result.manual == 1 and result.autofix == 0
    assert conn.replies[0][0] == 6002
    assert "human review" in conn.replies[0][1].lower()
    assert conn.resolved == []  # never resolve a thread we didn't fix

    # Phase 5: the fix report captures the resolved LLM tier/depth + resolution_reason.
    report = json.loads(
        (tmp_path / "runtime" / "prs" / "pr_7" / "fixes" / "copilot-6002.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["outcome"] == "justified_skip"
    assert report["resolved_llm"]["tier"] in {"haiku", "mistral-large", "opus", "opus-deep"}
    assert report["resolved_llm"]["resolution_reason"]
    assert report["resolved_llm"]["estimated_cost"] > 0.0
