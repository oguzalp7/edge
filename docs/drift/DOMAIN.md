# Domain: drift

- **Owner / DRI:** @edge-drift
- **Concepts:** `zero-token-drift-gate`, `domain-deed`, `atomic-state-store`

## Living Invariants
- **[INV-DRIFT-ZERO-TOKEN]** When changed files are disjoint from a domain's tracked globs in `CONTEXT.md`, drift checks skip model invocation and advance the baseline revision.
- **[INV-DRIFT-NO-FAKE-CLEAN]** Empty revision identifiers emit `ERROR` and never overwrite drift state as `CLEAN`.
- **[INV-DRIFT-ARCHIVE-SAFE]** Legacy ephemeral slice specs archive safely without overwriting prior archived entries on name collisions, while ephemeral issue cache entries are never archived or deleted.

## Adopted Patterns
- **[PAT-DRIFT-DIFF-GATE]** Deterministic ontology validation and revision-diff gating execute before any read-only model audit, skipping cleanly when no ontology exists.
- **[PAT-DRIFT-TAPU-DEED]** Pure abstract domain deeds defer path ownership and code mapping to `CONTEXT.md`, rejecting code leaks via `CODE_LEAK_IN_DOMAIN_DOC`.
- **[PAT-DRIFT-ISSUE-CONSOLIDATION]** Domain consolidation discovers cached issue specifications alongside legacy files and resolves tracker issues directly during contract synthesis.

```pseudo
IF ontology validation has ERROR THEN fail immediately
IF revision unchanged OR 0 tracked files changed THEN advance baseline -> CLEAN
ELSE run read-only domain audit -> CLEAN or DRIFT_DETECTED
```
