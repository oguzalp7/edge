# Domain: quality-gates

- **Owner / DRI:** @edge-quality
- **Concepts:** `deterministic-quality-gate`, `complexity-ceiling`, `goldfish-ephemeral-review`

## Living Invariants
- **[INV-QG-MIGRATION-LOCK]** Refactor operations never mutate database schemas or migration histories.
- **[INV-QG-CC-CEILING]** New and clean production functions maintain cyclomatic complexity `CC <= 10` with zero complexity regressions.
- **[INV-QG-READONLY-EXAMINER]** `EXAMINER` and `QA_ENGINEER` verify evidence strictly read-only against code and test outcomes without mutating implementation files.

## Adopted Patterns
- **[PAT-QG-DETERMINISTIC-GATE]** Static AST, complexity, purity, and mutation gates run deterministically before human or model review.
- **[PAT-QG-LEDGER-TRIAGE]** Smoke, radar, and security findings triage into structured ledger tickets rather than silent exclusions.
