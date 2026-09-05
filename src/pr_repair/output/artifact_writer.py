# --- L9_META ---
# l9_schema: 1
# origin: pr_repair_pipeline
# engine: pr_repair
# layer: [output]
# tags: [artifacts, reports, runtime, audit]
# owner: platform
# status: active
# --- /L9_META ---

from __future__ import annotations

from typing import Any

import yaml

from pr_repair.state_store import StateStore
from pr_repair.types import (
    Finding,
    FindingBundle,
    InterpretationReport,
    LearningPacket,
    RepairExecution,
    RepairPlan,
)
from pr_repair.verification.report_builder import (
    build_pr_result_markdown,
    build_verification_markdown,
)


def write_pr_artifacts(
    store: StateStore,
    bundle: FindingBundle,
    deduped_findings: list[Finding],
    classified_findings: list[Finding],
    plan: RepairPlan,
    execution: RepairExecution | None = None,
    pr_comment: str | None = None,
) -> InterpretationReport:
    pr_dir = f"prs/pr_{bundle.pr_ref.pr_number}"
    raw_count = (
        len(bundle.agent_review_findings)
        + len(bundle.github_check_findings)
        + len(bundle.github_comment_findings)
    )
    report = InterpretationReport(
        pr_number=bundle.pr_ref.pr_number,
        raw_count=raw_count,
        normalized_count=len(bundle.merged_findings),
        deduped_count=len(deduped_findings),
        protected_path_findings=sum(1 for finding in classified_findings if finding.protected_path),
        contract_violation_findings=sum(
            1 for finding in classified_findings if finding.contract_ids
        ),
        repairable_count=sum(1 for finding in classified_findings if finding.repairable),
        escalation_required_count=sum(
            1 for finding in classified_findings if finding.protected_path
        ),
        normalization_error_count=len(bundle.normalization_errors),
    )

    store.write_json(
        f"{pr_dir}/findings_normalized.json",
        [finding.model_dump(mode="json") for finding in bundle.merged_findings],
    )
    store.write_json(
        f"{pr_dir}/findings_deduped.json",
        [finding.model_dump(mode="json") for finding in deduped_findings],
    )
    store.write_json(
        f"{pr_dir}/findings_classified.json",
        [finding.model_dump(mode="json") for finding in classified_findings],
    )
    store.write_json(f"{pr_dir}/repair_plan.json", plan.model_dump(mode="json"))
    store.write_json(
        f"{pr_dir}/normalization_errors.json",
        [error.model_dump(mode="json") for error in bundle.normalization_errors],
    )
    store.write_markdown(f"{pr_dir}/interpretation_report.md", _build_report_markdown(report))

    if execution is not None:
        store.write_json(f"{pr_dir}/repair_execution.json", execution.model_dump(mode="json"))
        if execution.verification_result is not None:
            store.write_markdown(
                f"{pr_dir}/verification_report.md",
                build_verification_markdown(execution.verification_result),
            )
        store.write_markdown(
            f"{pr_dir}/pr_result_report.md",
            build_pr_result_markdown(execution),
        )
    if pr_comment:
        store.write_markdown(f"{pr_dir}/pr_commentary.md", pr_comment)
    return report


def write_run_artifacts(
    store: StateStore,
    candidate_prs: list[dict[str, Any]],
    merged_findings: list[Finding],
    plans: list[RepairPlan],
    executions: list[RepairExecution],
    reports: list[InterpretationReport],
) -> None:
    store.write_json("pr_inventory.json", candidate_prs)
    store.write_json(
        "findings_merged.json",
        [finding.model_dump(mode="json") for finding in merged_findings],
    )
    store.write_yaml(
        "repair_plans.yaml",
        [plan.model_dump(mode="json") for plan in plans],
    )
    if executions:
        store.write_json(
            "repair_executions.json",
            [execution.model_dump(mode="json") for execution in executions],
        )
        verification_sections = []
        result_sections = []
        for execution in executions:
            if execution.verification_result is not None:
                verification_sections.append(
                    build_verification_markdown(execution.verification_result)
                )
            result_sections.append(build_pr_result_markdown(execution))
        store.write_markdown(
            "verification_report.md",
            "\n\n".join(verification_sections) or "# Verification report\n",
        )
        store.write_markdown("pr_result_report.md", "\n\n".join(result_sections))
    store.write_markdown("phase_summary.md", _build_phase_summary(reports, plans, executions))


def write_learning_artifacts(
    store: StateStore,
    packets: list[LearningPacket],
    agent_payload: dict[str, Any],
    validator_payload: dict[str, Any],
) -> None:
    store.write_json(
        "learning_packets.json",
        [packet.model_dump(mode="json") for packet in packets],
    )
    store.write_yaml("AGENT_md_recommendations.yaml", agent_payload)
    store.write_yaml("validator_recommendations.yaml", validator_payload)
    store.write_markdown(
        "learning_report.md",
        _build_learning_report(packets, agent_payload, validator_payload),
    )


def _build_report_markdown(report: InterpretationReport) -> str:
    return (
        f"# Interpretation report for PR #{report.pr_number}\n\n"
        f"- Raw findings: `{report.raw_count}`\n"
        f"- Normalized findings: `{report.normalized_count}`\n"
        f"- Deduped findings: `{report.deduped_count}`\n"
        f"- Protected-path findings: `{report.protected_path_findings}`\n"
        f"- Contract-tagged findings: `{report.contract_violation_findings}`\n"
        f"- Repairable findings: `{report.repairable_count}`\n"
        f"- Escalation-required findings: `{report.escalation_required_count}`\n"
        f"- Normalization errors: `{report.normalization_error_count}`\n"
    )


def _build_phase_summary(
    reports: list[InterpretationReport],
    plans: list[RepairPlan],
    executions: list[RepairExecution],
) -> str:
    return yaml.safe_dump(
        {
            "interpreted_prs": [report.pr_number for report in reports],
            "plans_generated": len(plans),
            "executions_recorded": len(executions),
            "execution_statuses": [execution.status for execution in executions],
        },
        sort_keys=False,
    )


def _build_learning_report(
    packets: list[LearningPacket],
    agent_payload: dict[str, Any],
    validator_payload: dict[str, Any],
) -> str:
    return yaml.safe_dump(
        {
            "packet_count": len(packets),
            "packet_ids": [packet.packet_id for packet in packets],
            "agent_recommendation_sections": agent_payload.get("sections", {}),
            "validator_recommendation_sections": validator_payload.get("sections", {}),
        },
        sort_keys=False,
    )


def write_interpretation_artifacts(
    store: StateStore,
    bundle: FindingBundle,
    deduped_findings: list[Finding],
    classified_findings: list[Finding],
) -> InterpretationReport:
    """Compatibility wrapper for phase-3 artifact tests and callers."""
    from pr_repair.config import AppConfig
    from pr_repair.planning.repair_planner import build_repair_plan
    from pr_repair.types import ExecutionMode, TierLevel

    config = AppConfig(
        # Empty, not a placeholder string: this dry-run wrapper reaches only
        # build_repair_plan and write_pr_artifacts, neither of which reads
        # github_token (a GitHubConnector is built solely in run_pipeline and
        # pr_collector). Carrying a token-shaped literal here served no purpose
        # beyond looking like a credential.
        github_token="",
        github_repository=f"{bundle.pr_ref.repo_owner}/{bundle.pr_ref.repo_name}",
        verify_command=["python", "-c", "print('compat')"],
        mode=ExecutionMode.dry_run,
        output_dir=store.artifact_dir,
        write_ceiling=TierLevel.t1,
    )
    plan = build_repair_plan(bundle.pr_ref, classified_findings, config)
    report = write_pr_artifacts(store, bundle, deduped_findings, classified_findings, plan)
    # Preserve old root-level artifact contract for callers/tests that predate per-PR directories.
    store.write_json(
        "findings_normalized.json",
        [finding.model_dump(mode="json") for finding in bundle.merged_findings],
    )
    store.write_json(
        "findings_deduped.json",
        [finding.model_dump(mode="json") for finding in deduped_findings],
    )
    store.write_json(
        "findings_classified.json",
        [finding.model_dump(mode="json") for finding in classified_findings],
    )
    store.write_json(
        "normalization_errors.json",
        [error.model_dump(mode="json") for error in bundle.normalization_errors],
    )
    store.write_markdown("interpretation_report.md", _build_report_markdown(report))
    return report
