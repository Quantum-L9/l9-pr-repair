"""Real-shape adapter confirmation, backed by captured GitHub fixtures.

Unlike the synthetic fixtures in test_phase4_adapters.py, these load payloads
captured from live PRs on Quantum-L9/l9-pr-repair so a channel/login drift in a real
tool is caught. See tests/fixtures/tools/*.json for provenance.

Audit result (see fixtures for evidence):
  * Copilot     -> inline review threads (confirmed here); adapter actuates.
  * SonarCloud  -> issue-comment Quality-Gate summary, no inline threads on this
                   repo; adapter reads threads, so yields nothing (documented,
                   stays disabled until inline decoration is confirmed).
  * GitGuardian -> ggshield CI check only, no review comments (stays disabled).
  * CodeRabbit  -> not installed in scope (Unknown, stays disabled).
"""

import json
from pathlib import Path

from pr_repair import review_ingest
from pr_repair.ingestion.payload_parser import PayloadParser

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "tools"
FIXED_TS = "2026-07-01T00:00:00+00:00"


def test_copilot_real_review_thread_shape_confirms_adapter(tmp_path):
    out = tmp_path / "payload.json"

    rc = review_ingest.run(
        output=str(out),
        context=str(FIXTURES / "copilot_review_context.json"),
        generated_at=FIXED_TS,
    )

    assert rc == review_ingest.EXIT_PRODUCED
    parsed = PayloadParser(out).parse()
    # The one unresolved Copilot thread -> manual finding; the resolved one is filtered.
    assert [f.finding_id for f in parsed.manual_review_findings] == ["copilot-3502779796"]
    f = parsed.manual_review_findings[0]
    assert f.tool == "copilot"
    assert f.file_path == ".github/workflows/pr-checks.yml"
    assert f.line_start == 29 and f.line_end == 29
    assert parsed.autofix_findings == []


def test_sonar_evidence_fixture_documents_issue_comment_channel():
    # Guardrail: the committed evidence must keep asserting Sonar's real channel
    # is issue-comment (not review threads), which is why the adapter yields
    # nothing and sonarcloud stays disabled. If SonarCloud decoration changes the
    # shape, refresh this fixture and re-audit before enabling.
    evidence = json.loads((FIXTURES / "sonar_issue_comment.json").read_text(encoding="utf-8"))
    assert evidence["channel"] == "issue_comment"
    assert evidence["author_login"] == "sonarqubecloud[bot]"
    assert evidence["has_path_or_line"] is False
