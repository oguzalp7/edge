---
ticket_id: TICK-CORE-EXAMPLE
slug: example-refactor
track: core
target_rules:
  - RULE-ACTION-DB-LEAK
target_files:
  - src/actions/example.ts
metric_targets:
  db_leaks: 0
  max_cc: 10
door_type: two-way
behavior_preserved: true
tasks_axi_id: null
---

# Refactor Ticket: {{slug}}

## Intent & Scope
- **Track:** `{{track}}`
- **Target Rules:** `{{target_rules}}`
- **Target Files:** `{{target_files}}`
- **Door Classification:** `{{door_type}}`
- **Behavior Preserved:** `true` (Zero external API/behavioral regression)

## Acceptance Criteria
- [ ] **AC-1:** Existing characterization tests and `npx tsc --noEmit` remain green (`behavior_preserved: true`).
- [ ] **AC-2:** `MigrationGate` preserved (`src/db/schema/*` and `drizzle/*` untouched).
- [ ] **AC-3:** All `metric_targets` satisfied (`after` metrics non-null and meeting targets in `tools/gate.py --format json`).
- [ ] **AC-4:** 4-seal `RefactorReceipt` (`.edge/receipts/refactor/<slug>.json`) sealed with `ExaminerReceipt PASS` and distinct `examiner_cid != surgeon_cid`.
