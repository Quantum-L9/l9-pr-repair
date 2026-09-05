# ADR-001: Adopt .l9/corpus/ Shared Filesystem Convention for Cross-Repo Data Flow

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2026-07-04 |
| **Deciders** | L9 Platform Architecture |
| **Scope** | All Quantum-L9 constellation repos |

## Context

The L9 constellation consists of multiple repos that produce and consume intelligence artifacts:

- **@l9/harness** — produces golden principles, scanner rules, HITL policy
- **PR_Repair** — produces findings, telemetry, learning packets; consumes rules and policy
- **l9-ci-debt-lsp** — consumes compiled rules for IDE diagnostics

These repos need to share data bidirectionally. The data must flow automatically (no manual steps), extensibly (new repos can join without modifying existing ones), and reliably (no silent data loss).

## Decision

We adopt the **`.l9/corpus/` shared filesystem convention** as the sole integration surface between all L9 constellation repos.

### Convention Rules

1. Every participating repo contains a `.l9/corpus/` directory at its root
2. A `manifest.json` in that directory declares the repo's role (producer, consumer, or both) and which channels it reads/writes
3. Data flows through named **channels**: `rules`, `findings`, `telemetry`, `learning`, `policy`
4. Each channel has a defined schema version
5. Producers write to their channels atomically (write-then-rename)
6. Consumers read from channels idempotently (re-reading produces the same result)
7. No repo depends on another repo's internal implementation — only on channel schemas

### Sync Mechanism

For local development (repos checked out side-by-side), the `@l9/harness` package provides a `feed` command that watches and syncs between repos. For CI/CD, a simple `cp` or `rsync` from a sibling repo's `.l9/corpus/` directory suffices.

No central message bus. No API server. No database. Just files.

## Alternatives Considered

### A: Centralized API Server

A REST API that all repos call to push/pull data.

**Rejected because:**
- Requires infrastructure to operate (server, database, auth)
- Single point of failure
- Adds latency to every data exchange
- Requires all repos to have network access during development
- Violates the L9 principle of "no infrastructure to operate"

### B: Git Submodule Shared Repo

A single `l9-corpus` repo mounted as a submodule in every participating repo.

**Rejected because:**
- Git submodules are notoriously fragile
- Requires coordinated commits across repos
- Creates merge conflicts when multiple producers write simultaneously
- Adds cognitive overhead for developers

### C: npm Package with Embedded Sync

A monolithic npm package that handles all data flow internally.

**Rejected because:**
- Forces TypeScript/Node.js on Python repos (PR_Repair, l9-ci-debt-lsp)
- Requires installation and version management
- Couples the integration mechanism to a specific runtime
- Makes the integration surface opaque (hidden in package internals)

### D: GitHub Actions Relay

CI workflows that trigger cross-repo dispatches on push events.

**Rejected because:**
- Adds latency (minutes) to data propagation
- Requires CI credits for every sync
- Doesn't work during local development
- Creates complex dependency chains between workflows

## Consequences

### Positive

- **Zero infrastructure** — no servers, databases, or APIs to operate
- **Language agnostic** — Python, TypeScript, Go, anything that can read/write JSON
- **Instant local propagation** — file write → file read, no network round-trip
- **Trivially extensible** — new repo adds one file (`manifest.json`) to join
- **Auditable** — every channel has a `latest.json` with timestamps and producer identity
- **Fail-safe** — missing channels are no-ops, not crashes

### Negative

- **No built-in cross-machine sync** — requires external mechanism (git, rsync, or @l9/harness feed) for distributed teams
- **No access control** — any repo that can read the filesystem can read any channel
- **No schema evolution enforcement** — producers must manually maintain backward compatibility

### Mitigations

- Cross-machine sync is handled by `@l9/harness feed --watch` for development and by CI copy steps for production
- Access control is deferred until commercialization (internal-only for now)
- Schema evolution is enforced by convention: breaking changes require a new channel name (e.g., `rules-v2`)

## Implementation

| Repo | PR | Status |
|------|-----|--------|
| l9-pr-repair | [#20](https://github.com/Quantum-L9/l9-pr-repair/pull/20) | Open |
| l9-ci-debt-lsp | [#2](https://github.com/Quantum-L9/l9-ci-debt-lsp/pull/2) | Open |
| @l9/harness | Local update | In progress |

## References

- L9 Platform Doctrine §4: "Minimize infrastructure. Maximize convention."
- L9 Harness Engineering Blueprint D7: "The harness must be portable across repos without modification."
- L9 Architecture V1: "Constellation repos are autonomous but share a common governance substrate."
