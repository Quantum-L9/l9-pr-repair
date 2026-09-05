# --- L9_META ---
# l9_schema: 1
# origin: pr_repair_pipeline
# engine: pr_repair
# layer: [corpus, integration]
# tags: [highway, corpus, sync, output]
# owner: platform
# status: active
# --- /L9_META ---
"""Corpus Highway Writer — emits pipeline outputs to .l9/corpus/ channels.

This module writes normalized findings, telemetry, and learning packets
to the shared corpus directory, enabling automatic consumption by
@l9/harness and l9-ci-debt-lsp without PRs, CI, or manual intervention.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

CORPUS_DIR = ".l9/corpus"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_channel(repo_root: Path, channel: str) -> Path:
    """Ensure the channel directory exists and return its path."""
    channel_dir = repo_root / CORPUS_DIR / channel
    channel_dir.mkdir(parents=True, exist_ok=True)
    return channel_dir


def _write_payload(path: Path, payload: dict[str, Any]) -> None:
    """Write a JSON payload atomically (write-then-rename)."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.rename(path)
    log.info(
        "corpus: wrote %s (%d bytes)",
        path.relative_to(path.parent.parent.parent),
        path.stat().st_size,
    )


def write_findings(repo_root: Path, findings_payload: dict[str, Any]) -> Path:
    """Write normalized findings to the findings channel.

    Args:
        repo_root: Root of the repository containing .l9/corpus/
        findings_payload: A dict conforming to agent-review-payload.schema.json

    Returns:
        Path to the written file.
    """
    channel_dir = _ensure_channel(repo_root, "findings")
    envelope = {
        "schema": "l9.corpus_finding/v1",
        "produced_by": "Quantum-L9/l9-pr-repair",
        "produced_at": _utc_now(),
        "payload": findings_payload,
    }
    out_path = channel_dir / "latest.json"
    _write_payload(out_path, envelope)
    return out_path


def write_telemetry(repo_root: Path, telemetry_data: dict[str, Any]) -> Path:
    """Write autofix telemetry to the telemetry channel.

    Args:
        repo_root: Root of the repository containing .l9/corpus/
        telemetry_data: Telemetry dict with per-rule success rates

    Returns:
        Path to the written file.
    """
    channel_dir = _ensure_channel(repo_root, "telemetry")
    envelope = {
        "schema": "l9.corpus_telemetry/v1",
        "produced_by": "Quantum-L9/l9-pr-repair",
        "produced_at": _utc_now(),
        "payload": telemetry_data,
    }
    out_path = channel_dir / "latest.json"
    _write_payload(out_path, envelope)
    return out_path


def write_learning_packets(repo_root: Path, packets: list[dict[str, Any]]) -> Path:
    """Write learning packets to the learning channel.

    Args:
        repo_root: Root of the repository containing .l9/corpus/
        packets: List of learning packet dicts from pattern_extractor

    Returns:
        Path to the written file.
    """
    channel_dir = _ensure_channel(repo_root, "learning")
    envelope = {
        "schema": "l9.corpus_learning/v1",
        "produced_by": "Quantum-L9/l9-pr-repair",
        "produced_at": _utc_now(),
        "packet_count": len(packets),
        "payload": packets,
    }
    out_path = channel_dir / "latest.json"
    _write_payload(out_path, envelope)
    return out_path
