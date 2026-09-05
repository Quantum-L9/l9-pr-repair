import json
from pathlib import Path

import pytest

from pr_repair.config import AppConfig
from pr_repair.llm import build_llm_client
from pr_repair.llm.client import LLMUnavailableError, NullLLMClient, RouterClient
from pr_repair.llm.contract import LLMRequest, LLMResult
from pr_repair.llm.task_mapping import build_request, finding_complexity
from pr_repair.planning.llm_proposer import propose_repairs
from pr_repair.types import Finding, ReviewDisposition, Severity, SourceName


def _manual_finding(
    finding_id: str = "mr-1",
    *,
    protected: bool = False,
    severity: Severity = Severity.high,
) -> Finding:
    return Finding(
        finding_id=finding_id,
        pr_number=1,
        source_name=SourceName.agent_review,
        source_priority=110,
        severity=severity,
        category="architecture_boundary_violation",
        message="FastAPI imported inside engine layer",
        file_path="engine/server.py",
        line_start=3,
        line_end=3,
        review_disposition=ReviewDisposition.manual_review,
        protected_path=protected,
        repairable=False,
        fingerprint=f"fp-{finding_id}",
    )


class _FakeClient:
    def __init__(self, content: str = "", *, abstained: bool = False, error: str | None = None):
        self._content = content
        self._abstained = abstained
        self._error = error
        self.calls: list[LLMRequest] = []

    def generate(self, requests: list[LLMRequest]) -> list[LLMResult]:
        self.calls.extend(requests)
        return [
            LLMResult(
                finding_id=r.finding_id,
                content=self._content,
                model="anthropic/claude-sonnet",
                provider="openrouter",
                cost=0.002,
                abstained=self._abstained,
                error=self._error,
            )
            for r in requests
        ]


def _cfg() -> AppConfig:
    return AppConfig(github_token="t", github_repository="o/r")


def test_null_client_abstains() -> None:
    results = NullLLMClient().generate(
        [LLMRequest(finding_id="x", system_prompt="s", user_prompt="u")]
    )
    assert results[0].abstained is True


def test_build_llm_client_defaults_to_null() -> None:
    assert isinstance(build_llm_client(_cfg()), NullLLMClient)


def test_build_llm_client_returns_router_when_enabled() -> None:
    cfg = _cfg().model_copy(update={"llm_enabled": True})
    assert isinstance(build_llm_client(cfg), RouterClient)


def test_finding_complexity_maps_severity() -> None:
    assert finding_complexity(_manual_finding(severity=Severity.critical)) == "critical"
    assert finding_complexity(_manual_finding(severity=Severity.low)) == "low"


def test_build_request_includes_context_and_bounds(tmp_path: Path) -> None:
    (tmp_path / "engine").mkdir()
    (tmp_path / "engine" / "server.py").write_text(
        "\n".join(f"l{i}" for i in range(1, 30)), encoding="utf-8"
    )
    req = build_request(_manual_finding(), tmp_path, "implementer-bot")
    assert req.task_type == "code_generation"
    assert req.complexity == "high"
    assert "architecture_boundary_violation" in req.user_prompt
    assert "file_context" in req.user_prompt


def test_router_client_uses_injected_transport() -> None:
    def transport(payload: list[dict]) -> list[dict]:
        return [{"finding_id": p["finding_id"], "content": "ok", "cost": 0.01} for p in payload]

    client = RouterClient(shim_path=Path("unused"), transport=transport)
    results = client.generate([LLMRequest(finding_id="a", system_prompt="s", user_prompt="u")])
    assert results[0].content == "ok"
    assert results[0].cost == 0.01


def test_router_client_missing_shim_raises() -> None:
    client = RouterClient(shim_path=Path("/no/such/shim.mjs"))
    with pytest.raises(LLMUnavailableError, match="router shim not found"):
        client.generate([LLMRequest(finding_id="a", system_prompt="s", user_prompt="u")])


def test_propose_repairs_with_null_client_all_abstain(tmp_path: Path) -> None:
    proposals = propose_repairs([_manual_finding()], NullLLMClient(), tmp_path, "implementer-bot")
    assert len(proposals) == 1
    assert proposals[0].abstained is True


def test_propose_repairs_skips_protected_paths(tmp_path: Path) -> None:
    fake = _FakeClient(content="{}")
    proposals = propose_repairs(
        [_manual_finding(protected=True)], fake, tmp_path, "implementer-bot"
    )
    assert proposals == []
    assert fake.calls == []  # protected findings never reach the model


def _write_target(root: Path, *lines: str, path: str = "engine/server.py") -> Path:
    """Materialize the file a proposal targets.

    The proposer reads the block it proposes to replace from disk, so a
    proposal for a file that does not exist now abstains. Tests that expect an
    actionable instruction must provide the source.
    """
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def test_propose_repairs_parses_valid_patch(tmp_path: Path) -> None:
    _write_target(tmp_path, "import os", "", "from fastapi import FastAPI")
    content = json.dumps(
        {
            "op": "replace_range",
            "line_start": 3,
            "line_end": 3,
            "replacement": "x = 1",
            "rationale": "fix",
        }
    )
    proposals = propose_repairs([_manual_finding()], _FakeClient(content=content), tmp_path, "c")
    p = proposals[0]
    assert p.abstained is False
    assert p.instruction is not None
    assert p.instruction["op"] == "replace_range"
    assert p.instruction["file_path"] == "engine/server.py"
    assert p.instruction["source"] == "llm_router"
    assert p.model == "anthropic/claude-sonnet"


def test_llm_proposal_binds_the_instruction_to_on_disk_content(tmp_path: Path) -> None:
    """The model supplies line numbers; the block comes from the file itself.

    Without this the applier had nothing to verify a model-chosen range
    against, and a hallucinated or shifted span overwrote whatever occupied
    those line numbers.
    """
    _write_target(tmp_path, "import os", "", "from fastapi import FastAPI")
    content = json.dumps(
        {"op": "replace_range", "line_start": 3, "line_end": 3, "replacement": "x = 1"}
    )
    proposals = propose_repairs([_manual_finding()], _FakeClient(content=content), tmp_path, "c")
    instruction = proposals[0].instruction
    assert instruction is not None
    assert instruction["expected_block"] == ["from fastapi import FastAPI"]


def test_llm_proposal_abstains_when_the_target_file_is_missing(tmp_path: Path) -> None:
    """No file, no block, no instruction -- abstain rather than propose blind."""
    content = json.dumps(
        {"op": "replace_range", "line_start": 3, "line_end": 3, "replacement": "x = 1"}
    )
    proposals = propose_repairs([_manual_finding()], _FakeClient(content=content), tmp_path, "c")
    assert proposals[0].abstained is True
    assert proposals[0].instruction is None


def test_llm_proposal_abstains_when_the_model_range_exceeds_the_file(tmp_path: Path) -> None:
    """A range past end-of-file is a hallucinated range, not a patchable one."""
    _write_target(tmp_path, "only one line")
    content = json.dumps(
        {"op": "replace_range", "line_start": 3, "line_end": 3, "replacement": "x = 1"}
    )
    proposals = propose_repairs([_manual_finding()], _FakeClient(content=content), tmp_path, "c")
    assert proposals[0].abstained is True
    assert proposals[0].instruction is None


def test_propose_repairs_handles_model_abstain(tmp_path: Path) -> None:
    proposals = propose_repairs(
        [_manual_finding()],
        _FakeClient(content='{"abstain": true, "rationale": "too risky"}'),
        tmp_path,
        "c",
    )
    assert proposals[0].abstained is True
    assert proposals[0].rationale == "too risky"


def test_propose_repairs_handles_non_json(tmp_path: Path) -> None:
    proposals = propose_repairs(
        [_manual_finding()], _FakeClient(content="sorry I cannot"), tmp_path, "c"
    )
    assert proposals[0].abstained is True
    assert any("non-JSON" in d for d in proposals[0].diagnostics)


def test_propose_repairs_rejects_malformed_patch(tmp_path: Path) -> None:
    # missing replacement
    content = json.dumps({"op": "replace_range", "line_start": 3, "line_end": 3})
    proposals = propose_repairs([_manual_finding()], _FakeClient(content=content), tmp_path, "c")
    assert proposals[0].abstained is True
    assert proposals[0].instruction is None


def test_propose_repairs_rejects_repo_wide_finding_without_file_path(tmp_path: Path) -> None:
    # A repo-wide manual finding carries no file_path; an LLM patch instruction
    # cannot target a file, so it must never become an applicable instruction.
    finding = _manual_finding().model_copy(update={"file_path": None})
    content = json.dumps(
        {
            "op": "replace_range",
            "line_start": 3,
            "line_end": 3,
            "replacement": "x = 1",
            "rationale": "fix",
        }
    )
    proposals = propose_repairs([finding], _FakeClient(content=content), tmp_path, "c")
    assert proposals[0].instruction is None


def test_propose_repairs_router_unavailable_degrades_gracefully(tmp_path: Path) -> None:
    class _Down:
        def generate(self, requests):
            raise LLMUnavailableError("node missing")

    proposals = propose_repairs([_manual_finding()], _Down(), tmp_path, "c")
    assert proposals[0].abstained is True
    assert any("unavailable" in d for d in proposals[0].diagnostics)
