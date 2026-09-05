from pr_repair.learning.validator_recommender import build_validator_recommendations
from pr_repair.types import LearningPacket


def test_build_validator_recommendations_is_review_only() -> None:
    packets = [
        LearningPacket(
            packet_id="lp-2",
            source_prs=[52],
            repeated_failures=["approval_required", "rolled_back_verification_failed"],
            agent_md_recommendations=[],
            validator_recommendations=["Add a plan safety validator for protected paths."],
            confidence=0.7,
        )
    ]

    payload = build_validator_recommendations(packets)

    assert payload["target_system"] == "external_validator_suite"
    assert payload["write_policy"] == "review_only_no_direct_mutation"
    assert (
        "Add a plan safety validator for protected paths."
        in payload["sections"]["new_rule_candidates"]
    )
