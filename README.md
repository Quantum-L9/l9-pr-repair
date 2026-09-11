# pr_repair

`pr_repair` is a local-first, repo-aware, governance-first autonomous PR repair pipeline for L9-governed repositories.

## What it is

A deterministic repair pipeline that collects repository and PR signals, normalizes findings, deduplicates and clusters them, classifies defects, plans bounded repairs, applies exact-match patches, verifies the result, rolls back failed executions, and emits inspectable artifacts.

## What it is not

- It is not an uncontrolled coding agent.
- It does not create pull requests.
- It does not bypass approval gates.
- It does not mutate protected paths without policy approval.
- It does not invent repair behavior outside validated code paths.

## Canonical pipeline

1. signal_intake
2. normalization
3. deduplication
4. clustering
5. candidate_generation
6. classification
7. priority_resolution
8. repair_planning
9. approval_gate
10. workspace_isolation
11. patch_generation
12. verification
13. rollback_or_learn
14. governance_recommendations

## Quickstart

```bash
python -m pip install -e .
pytest -q
```

Run in dry mode before any repair execution:

```bash
pr-repair --mode dry-run
```

## Safety model

- Local-first execution is the default operating assumption.
- Human approval is required when configured thresholds are exceeded.
- Protected-path policy is enforced before write behavior.
- Patch application uses exact-match instructions.
- Verification failure triggers rollback to a backup ref.
- Artifacts are emitted for review and audit.

## Governance model

Governance lives in approval gates, path policy, config ceilings, execution modes, verification requirements, and artifact output. The system MUST preserve bounded mutation and inspectable execution.

## Artifact model

Runtime artifacts capture findings, plans, execution results, verification reports, learning packets, and governance recommendations. Artifacts are operational evidence, not decorative logs.

## Local-first principle

The system MUST be runnable against a local checkout. Hosted orchestration is a future deployment path, not a prerequisite for the canonical runtime.

## GitHub PR Loop MVP

The system can be wired as a repair bot for existing same-repo PR branches.

Supported MVP behavior:

- receive GitHub PR, review, check, and workflow events
- verify webhook signatures
- wait for CI and review signals
- ingest and normalize findings
- plan bounded repairs
- require approval gates before mutation
- commit repairs back to the existing PR branch
- wait for CI rerun
- repeat until clean, blocked, or max attempts reached

Unsupported initially:

- fork PRs
- creating new PRs
- automatic merge
- protected branch direct mutation
- hosted multi-tenant orchestration

## Repository manifest

`MANIFEST.md` is the SDK-rendered inventory of this repository's tracked files.
It is the input `l9-assurance` derives the `L9.CI.REPOSITORY_METADATA` control
from, through the SDK's `l9.repository-metadata` observation: the committed
manifest is compared against what the SDK builds from repository truth, and a
missing or stale manifest fails that control. The file is owned by the
`l9-ci manifest generate` CLI and is never hand-edited. Regenerate it whenever
the set of tracked files changes:

```bash
l9-ci manifest generate --repository-root . --output MANIFEST.md --tracked-only
l9-ci manifest check    --repository-root . --output MANIFEST.md --tracked-only
```

`MANIFEST.json` is unrelated: it is the pack inventory of the
`pr_repair_github_pr_loop_pack` distribution and is not read by Assurance.
