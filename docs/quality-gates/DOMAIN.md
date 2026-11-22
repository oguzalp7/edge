# Domain: quality-gates

- **Paths:** `tools/gate.py`, `tools/rules.py`, `tools/audit/**`, `tools/ui_audit/**`, `tools/test_audit/**`, `tools/radar/**`, `tools/mutator/**`, `tools/brigade/qa_fiber.py`, `tools/brigade/security_audit.py`, `tools/brigade/smoke_routes.py`, `skills/edge-audit/**`, `skills/edge-ui-audit/**`, `skills/edge-tests-audit-typescript/**`, `skills/edge-radar/**`, `skills/edge-mutator/**`, `skills/edge-security-audit/**`, `agents/examiner.md`, `agents/qa-engineer.md`
- **Owner / DRI:** @edge-quality
- **Concepts:** `deterministic-quality-gate`, `complexity-ceiling`, `goldfish-ephemeral-review`

## Core Invariants
- **[INV-QG-MIGRATION-LOCK]** Refactor operations never mutate database schema or migration files.
  *Enforced by:* `tests/test_gate.py`, `tools/gate.py`
- **[INV-QG-CC-CEILING]** New and clean Python/TS functions maintain cyclomatic complexity `CC <= 10` with zero complexity regressions.
  *Enforced by:* `tests/test_gate.py`, `tests/test_crapper.py`, `tools/gate.py`, `tools/audit/crapper.py`
- **[INV-QG-READONLY-EXAMINER]** `EXAMINER` and `QA_ENGINEER` verify evidence strictly read-only against code and tests without mutating production code.
  *Enforced by:* `tests/test_qa_fiber.py`, `agents/examiner.md`, `agents/qa-engineer.md`

## Adopted Patterns
- **[PAT-QG-DETERMINISTIC-GATE]** `EdgeVerificationGate` runs static AST/regex/complexity gates (`tools/rules.py`, `tools/audit/**`, `tools/mutator/**`) before LLM review.
  *Enforced by:* `tests/test_audit_suite.py`, `tests/test_dead_code.py`, `tests/test_dryer.py`, `tests/test_ts_discipline.py`, `tests/test_mutator.py`, `tools/gate.py`
- **[PAT-QG-LEDGER-TRIAGE]** `LedgerEngine` and smoke/security auditors triage findings into deterministic `.edge/ledger/` tickets instead of silent ignores.
  *Enforced by:* `tests/test_radar_quality_rules.py`, `tools/radar/ledger.py`, `tools/brigade/smoke_routes.py`
