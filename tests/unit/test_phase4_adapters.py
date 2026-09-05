from pr_repair.server.github_webhook import NormalizedPREvent
from pr_repair.tools.coderabbit import CodeRabbitAdapter
from pr_repair.tools.gitguardian import GitGuardianAdapter
from pr_repair.tools.registry import adapter_for_event
from pr_repair.tools.sonar import SonarAdapter
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


def _thread(login: str, body: str, *, path="svc/x.py", line=10, resolved=False) -> dict:
    return {
        "id": "PRRT_1",
        "isResolved": resolved,
        "path": path,
        "line": line,
        "comments": {
            "nodes": [
                {
                    "id": "PRRC",
                    "databaseId": 42,
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

    def get_review_threads(self, owner, repo, pr):
        return self._threads


def _event(tool: str | None) -> NormalizedPREvent:
    return NormalizedPREvent(
        "pull_request_review", "submitted", "review_completed", "owner/repo", 7, "sha", {}, tool
    )


# --- CodeRabbit ---------------------------------------------------------------


def test_coderabbit_suggestion_is_autofix() -> None:
    adapter = CodeRabbitAdapter()
    body = "Simplify.\n```suggestion\nreturn x\n```"
    findings = adapter.to_payload_findings(
        adapter.read_findings(_pr(), _Conn([_thread("coderabbitai[bot]", body)]))
    )
    assert findings[0]["_disposition"] == "autofix"
    assert findings[0]["replacement_text"] == "return x"
    assert findings[0]["tool"] == "coderabbit"


def test_coderabbit_rejects_non_coderabbit_threads() -> None:
    adapter = CodeRabbitAdapter()
    assert adapter.read_findings(_pr(), _Conn([_thread("some-human", "hi")])) == []


# --- Sonar --------------------------------------------------------------------


def test_sonar_extracts_rule_and_is_manual() -> None:
    adapter = SonarAdapter()
    body = "Define a constant instead of duplicating this literal (python:S1192)."
    findings = adapter.to_payload_findings(
        adapter.read_findings(_pr(), _Conn([_thread("sonarcloud[bot]", body)]))
    )
    assert findings[0]["rule_id"] == "python:S1192"
    assert findings[0]["_disposition"] == "manual_review"
    assert findings[0]["tool"] == "sonarcloud"


def test_sonar_secrets_rule_is_security() -> None:
    adapter = SonarAdapter()
    body = "Hardcoded credential detected (secrets:S6290)."
    findings = adapter.to_payload_findings(
        adapter.read_findings(_pr(), _Conn([_thread("sonarqubecloud[bot]", body)]))
    )
    assert findings[0]["category"] == "security_issue"


# --- GitGuardian --------------------------------------------------------------


def test_gitguardian_is_critical_security_and_manual() -> None:
    adapter = GitGuardianAdapter()
    body = "A generic API key was found in this file."
    findings = adapter.to_payload_findings(
        adapter.read_findings(_pr(), _Conn([_thread("gitguardian[bot]", body)]))
    )
    f = findings[0]
    assert f["category"] == "security_issue"
    assert f["severity"] == "critical"
    assert f["_disposition"] == "manual_review"  # secrets are never auto-patched
    assert "secret" in f["tags"]


# --- Registry gating ----------------------------------------------------------


def test_registry_gates_by_enabled_tools() -> None:
    # coderabbit event, but only copilot enabled -> no adapter
    assert adapter_for_event(_event("coderabbit"), enabled={"copilot"}) is None
    assert isinstance(
        adapter_for_event(_event("coderabbit"), enabled={"coderabbit"}), CodeRabbitAdapter
    )
    assert isinstance(
        adapter_for_event(_event("gitguardian"), enabled={"gitguardian"}), GitGuardianAdapter
    )
    # no gate -> all registered adapters resolve
    assert adapter_for_event(_event("sonarcloud")) is not None
