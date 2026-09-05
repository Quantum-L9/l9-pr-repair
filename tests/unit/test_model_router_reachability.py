"""Reachability guard: every ModelTier must be selectable.

EIE's search_optimizer.py has a documented dead-tier bug — SONAR_DEEP_RESEARCH is
defined and cost-modeled but _pick_model() never returns it. This test ensures
PR_Repair's port does not inherit that: every ModelTier is reachable from some
(complexity, signals) input, and every tier has a positive cost.
"""

from pr_repair.llm.model_router import (
    COST_PER_TIER,
    Depth,
    FindingSignals,
    ModelTier,
    resolve_llm_config,
)

_COMPLEXITIES = ["trivial", "low", "medium", "high", "critical"]
_ATTEMPTS = [0, 1, 2, 3]


def test_every_model_tier_is_reachable() -> None:
    reached: set[ModelTier] = set()
    for complexity in _COMPLEXITIES:
        for attempts in _ATTEMPTS:
            cfg = resolve_llm_config(
                complexity, None, FindingSignals(prior_failed_attempts=attempts)
            )
            reached.add(cfg.tier)
    assert reached == set(ModelTier), f"unreachable tiers: {set(ModelTier) - reached}"


def test_every_depth_is_reachable() -> None:
    reached = {resolve_llm_config(c, None, None).depth for c in _COMPLEXITIES}
    assert reached == set(Depth)


def test_every_tier_has_positive_cost() -> None:
    for tier in ModelTier:
        assert COST_PER_TIER[tier] > 0.0


def test_resolution_reason_and_cost_are_populated_for_all_inputs() -> None:
    for complexity in _COMPLEXITIES:
        cfg = resolve_llm_config(complexity, None, None)
        assert cfg.resolution_reason
        assert cfg.estimated_cost > 0.0
        assert cfg.model == cfg.tier.value
