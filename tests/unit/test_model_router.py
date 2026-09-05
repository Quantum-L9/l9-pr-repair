from pr_repair.llm.model_router import (
    Depth,
    FindingSignals,
    ModelTier,
    resolve_for_finding,
    resolve_llm_config,
)
from pr_repair.routing.fix_matrix import FixStrategy
from pr_repair.types import Finding, Severity, SourceName


def _finding(severity: Severity = Severity.medium) -> Finding:
    return Finding(
        finding_id="f",
        pr_number=1,
        source_name=SourceName.agent_review,
        source_priority=110,
        severity=severity,
        category="review_comment",
        message="m",
        fingerprint="fp",
    )


def test_complexity_maps_to_default_tiers() -> None:
    assert resolve_llm_config("medium").tier is ModelTier.MISTRAL_LARGE
    assert resolve_llm_config("high").tier is ModelTier.OPUS
    assert resolve_llm_config("critical").tier is ModelTier.OPUS_DEEP
    assert resolve_llm_config("low").tier is ModelTier.HAIKU


def test_mistral_for_medium_opus_for_high_policy() -> None:
    # The headline policy: Mistral Large = medium, Opus = high.
    assert resolve_for_finding(_finding(Severity.medium)).model == "mistral-large"
    assert resolve_for_finding(_finding(Severity.high)).model == "opus"


def test_matrix_strategy_pins_tier_and_depth() -> None:
    strategy = FixStrategy(kind="llm", tier="opus", depth="high", matched_by="category")
    cfg = resolve_llm_config("low", strategy)  # complexity would give haiku, matrix overrides
    assert cfg.tier is ModelTier.OPUS
    assert cfg.depth is Depth.HIGH
    assert "matrix pinned" in cfg.resolution_reason


def test_repeated_failures_escalate_tier() -> None:
    base = resolve_llm_config("medium", None, FindingSignals(prior_failed_attempts=0))
    escalated = resolve_llm_config("medium", None, FindingSignals(prior_failed_attempts=2))
    assert base.tier is ModelTier.MISTRAL_LARGE
    assert escalated.tier is ModelTier.OPUS  # bumped one rung up the ladder
    assert "escalate" in escalated.resolution_reason


def test_effort_only_for_reasoning_tiers() -> None:
    assert resolve_llm_config("low").effort is None  # haiku
    assert resolve_llm_config("high").effort == "medium"  # opus, no prior failures
    assert (
        resolve_llm_config("high", None, FindingSignals(prior_failed_attempts=1)).effort == "high"
    )


def test_invalid_matrix_tier_falls_back_to_complexity() -> None:
    strategy = FixStrategy(kind="llm", tier="gpt-9-ultra", depth="sideways", matched_by="category")
    cfg = resolve_llm_config("medium", strategy)
    assert cfg.tier is ModelTier.MISTRAL_LARGE  # unknown tier ignored
    assert cfg.depth is Depth.MEDIUM  # unknown depth ignored


def test_resolved_hints_reach_the_router_transport(tmp_path) -> None:
    # ADR 0001: depth/effort/tier resolved by model_router must arrive unchanged
    # at the transport (the shim relays them to L9LLMRouter.execute).
    from pathlib import Path

    from pr_repair.llm.client import RouterClient
    from pr_repair.llm.task_mapping import build_request

    strategy = FixStrategy(kind="llm", tier="opus", depth="high", matched_by="category")
    resolved = resolve_llm_config("high", strategy, FindingSignals(prior_failed_attempts=1))
    request = build_request(_finding(Severity.high), tmp_path, "impl-bot", resolved=resolved)

    assert request.tier == "opus" and request.depth == "high" and request.effort == "high"

    captured: list[dict] = []

    def transport(payload: list[dict]) -> list[dict]:
        captured.extend(payload)
        return [{"finding_id": p["finding_id"], "content": "ok"} for p in payload]

    RouterClient(shim_path=Path("unused"), transport=transport).generate([request])

    assert captured[0]["tier"] == "opus"
    assert captured[0]["depth"] == "high"
    assert captured[0]["effort"] == "high"
