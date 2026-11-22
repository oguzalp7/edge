# Domain: drift

- **Paths:** `tools/drift/**`, `skills/edge-drift/**`
- **Owner / DRI:** @edge-drift
- **Concepts:** `zero-token-drift-gate`, `domain-deed`, `atomic-state-store`

## Core Invariants
- **[INV-DRIFT-ZERO-TOKEN]** When git diff shows zero changed files matching a domain's `Paths:`, `check_drift` never invokes `agy` and advances `last_checked_sha` to `HEAD`.
  *Enforced by:* `tests/test_drift.py`, `tools/drift/scanner.py`
- **[INV-DRIFT-NO-FAKE-CLEAN]** Empty git `HEAD` SHA returns `ERROR` and never overwrites `DriftStateStore` as `CLEAN`.
  *Enforced by:* `tests/test_drift.py`, `tools/drift/scanner.py`, `tools/drift/cli.py`
- **[INV-DRIFT-ARCHIVE-SAFE]** `archive_ephemeral_spec` moves completed slice specs into `.edge/archive/specs/` without overwriting existing archived specs on timestamp collision.
  *Enforced by:* `tests/test_drift.py`, `tools/drift/scanner.py`

## Adopted Patterns
- **[PAT-DRIFT-DIFF-GATE]** Deterministic `validate_ontology` and `git diff --name-only` gates run before any read-only `agy` audit, skipping ontology checks cleanly when `CONTEXT.md` and `docs/*/DOMAIN.md` are absent.
  *Enforced by:* `tests/test_drift.py`, `tests/test_context_system.py`, `tools/drift/scanner.py`
- **[PAT-DRIFT-TAPU-DEED]** Canonical `docs/<domain>/DOMAIN.md` deeds take precedence over legacy `docs/domains/*.md`, rejecting `docs/domains/DOMAIN.md` as a collision.
  *Enforced by:* `tests/test_drift.py`, `tools/drift/models.py`
