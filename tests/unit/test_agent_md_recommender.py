from pr_repair.learning.agent_md_recommender import build_agent_md_recommendations
from pr_repair.types import LearningPacket


def test_build_agent_md_recommendations_is_review_only() -> None:
    packets = [
        LearningPacket(
            packet_id="lp-1",
            source_prs=[41],
            repeated_failures=["approval_required", "verification_make_agent_check_failure"],
            agent_md_recommendations=["Require make agent-check parity before approval."],
            validator_recommendations=[],
            confidence=0.8,
        )
    ]

    payload = build_agent_md_recommendations(packets)

    assert payload["target_document"] == "AGENT.md"
    assert payload["write_policy"] == "review_only_no_direct_mutation"
    assert (
        "Require make agent-check parity before approval."
        in payload["sections"]["stronger_preflight_rules"]
    )
