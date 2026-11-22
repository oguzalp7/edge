---
name: edge-drift
description: Git-diff gated domain contract drift detector, ephemeral spec archiver, and domain consolidator. Guards against invariant rot and scope drift between specs and code.
---

# 🛡️ /edge-drift — Git-Diff Gated Domain Contract Drift Engine

> *"Specs are temporary construction scaffolding; Domain Deeds ('Tapu') are permanent land titles. When a vertical slice is delivered, the scaffolding is archived, and the canonical domain deed records the permanent invariants and boundaries."*

`edge-drift` enforces architectural integrity and eliminates specification rot across long-running codebases through a **zero-token git-diff gating engine**, **spec consolidation**, and a **two-way reconciliation protocol**.

---

## 🏛️ The "Scaffolding vs. Domain Deed (Tapu)" Doctrine

In fast-moving agentic workflows, specifications tend to scatter and rot:
1. **İskele (Ephemeral Task/Slice Specs - `.edge/specs/*.md`):**  
   Temporary construction scaffolding written by `SPEC_WRITER` to execute a single vertical slice. Once tests are green and the code is merged, keeping task specs active causes context noise, hallucinations, and confusion. They must be safely moved to `.edge/archive/specs/`.
2. **Tapu (Canonical Domain Deeds - `docs/<domain>/DOMAIN.md`):**  
   Pure abstract, 100% code-free behavioral deeds ("Tapu") declaring `- **Owner / DRI:**`, `- **Concepts:**`, living invariants (`[INV-*]`), adopted patterns (`[PAT-*]`), and optional `mermaid`/`pseudo` diagrams (guarded by `CODE_LEAK_IN_DOMAIN_DOC`). Domain-to-glob ownership lives canonically in `CONTEXT.md` `## Domain Map` (falling back to `DOMAIN.md` `Paths:` or legacy `docs/domains/<domain>.md` only when absent; `docs/domains/DOMAIN.md` is rejected as a collision).

```
 [ Vertical Slice Complete ]
              │
              ├──> archive_ephemeral_spec() ──> .edge/archive/specs/ (Archived)
              │
              └──> consolidate_domain()     ──> docs/<domain>/DOMAIN.md (or legacy docs/domains/<domain>.md)
```

---

## 📋 Canonical `DOMAIN.md`, `CONTEXT.md` Bridge & Legacy YAML Standard

Canonical domain deeds live at `docs/<domain>/DOMAIN.md` with pure abstract metadata (`# Domain: <name>`, `- **Owner / DRI:**`, `- **Concepts:**`, bullet-defined `**[INV-*]**` and `**[PAT-*]**`), while `CONTEXT.md` (`## Domain Map` + `## Closed Concept Glossary`) acts as the single code bridge and code/test `@invariants` headers populate `invariant_index`. Legacy deeds under `docs/domains/<domain>.md` remain supported using leading YAML frontmatter defining `domain` and `tracked_paths`:

### Format 1: Block List Syntax
```yaml
---
domain: bookings
tracked_paths:
  - src/lib/bookings/**
  - src/actions/bookings.ts
  - src/db/schema/bookings.ts
---

# Bookings Domain Contract

## Core Invariants
1. Booking slots can never overlap for the same resource.
2. Direct database mutations outside `src/lib/bookings/repository.ts` are strictly forbidden.

## Domain Boundaries
- Owns: Reservations, cancellation policies, slot availability.
- Rejects: Payment processing (delegated to `payments` domain).

## Intentional Anchors & Deferred Scope
- Recurring multi-week booking series is deferred to Phase 2.
```

### Format 2: Inline List Syntax
```yaml
---
domain: orders
tracked_paths: ["src/lib/orders/**", "src/actions/orders.ts"]
---
```

### Path Matching Rules
- `src/lib/bookings/**`: Matches all files in `src/lib/bookings/` and all nested subdirectories.
- `src/actions/bookings.ts`: Matches exact file.
- `src/lib/**/*.ts`: Matches any TypeScript file under `src/lib/`.

---

## 🔒 The Zero-Token Gated Verification Invariant

`edge-drift check` executes with near-zero latency and zero token cost when code is untouched:

```
                  [ edge-drift check <repo> ]
                              │
                              ▼
       validate_ontology() + Read docs/*/DOMAIN.md & docs/domains/*.md
                              │
                              ▼
            Compare HEAD SHA vs last_checked_sha
               │                              │
         (SHA Unchanged)               (SHA Advanced)
               │                              │
               ▼                              ▼
      [ CLEAN: 0 Tokens ]           git diff --name-only <base>..HEAD
                                              │
                              ┌───────────────┴───────────────┐
                              │                               │
                       0 Matched Files              >= 1 Matched Files
                              │                               │
                              ▼                               ▼
                     Advance baseline SHA          Invoke Read-Only Auditor
                     [ CLEAN: 0 Tokens ]           (gemini-3.8-flash-high)
                                                              │
                                              ┌───────────────┴───────────────┐
                                              │                               │
                                         "NO_DRIFT"                    Findings Logged
                                              │                               │
                                              ▼                               ▼
                                     Advance baseline SHA            [ DRIFT_DETECTED ]
                                     [ CLEAN: 1 Call ]               Exit Code 1
```

1. **SHA Match:** If current `HEAD == last_checked_sha`, 0 git diffs and 0 LLM calls are made.
2. **Disjoint Code Changes:** If git diff shows commits only in `src/other/**` (not in `tracked_paths`), the baseline SHA is updated automatically with **ZERO LLM CALLS**.
3. **Triggered LLM Audit:** Only when live code matching `tracked_paths` has changed does `agy` audit the diff across 4 strict categories:
   - `BROKEN_INVARIANT`: Live code violates an invariant stated in the domain contract.
   - `LOGIC_SHORTCUT`: A temporary shortcut, hack, or leak was introduced bypassing domain boundaries.
   - `ANCHOR_DRIFT`: An intentional anchor or deferred scope was altered or prematurely implemented.
   - `DOC_OUTDATED`: Live code legitimately evolved or was refactored, but the domain document was not updated.

---

## ⚡ CLI Reference

### 1. Discover Specs
Discovers canonical domain contracts vs scattered ephemeral/task specs:
```bash
python tools/drift/cli.py discover .
```

### 2. Check Drift & Ontology
Audits `CONTEXT.md`, `docs/<domain>/DOMAIN.md`, code header tags (`validate_ontology()`), and domain contracts against live code:
```bash
# Deterministic zero-LLM ontology check only
python tools/drift/cli.py check . --ontology-only

# Automated ontology + drift check in CI / pre-push
python tools/drift/cli.py check .

# Custom model specification
python tools/drift/cli.py check . --model gemini-3.8-flash-high
```

### 3. Consolidate Domain Contract
Distills scattered specs and live code into a domain deed (`docs/<domain>/DOMAIN.md` or legacy `docs/domains/<domain>.md`):
```bash
python tools/drift/cli.py consolidate . \
  --domain bookings \
  --paths "src/lib/bookings/**,src/actions/bookings.ts" \
  --sources ".edge/specs/slice-booking-calendar.md,.edge/specs/slice-cancellation.md" \
  --archive-sources
```

---

## 🔄 Zero-Chores Two-Way Reconciliation Protocol

When `edge-drift check` reports `DRIFT_DETECTED`, the engineer or agent selects one of two deterministic reconciliation paths:

### 🌟 Path A: Intentional Code Evolution (Update the Deed)
If the live code changes represent intentional, approved architectural enhancements:
1. Edit `docs/<domain>/DOMAIN.md` (or legacy `docs/domains/<domain>.md`) to reflect the updated business invariants or boundary definitions.
2. Mark the domain (or all domains) clean at current HEAD:
   ```bash
   python tools/drift/cli.py check . --mark-clean <domain>
   python tools/drift/cli.py check . --mark-clean all
   ```
3. Commit the updated domain contract with your feature or refactor branch.

### 🚨 Path B: Broken Invariant or Shortcut (Fix the Implementation)
If the live code took an illegal shortcut (e.g. bypassing repository boundary, importing raw DB queries in UI actions):
1. Review findings in `.edge/drift/latest-drift-report.md`.
2. File an immediate remediation ticket via `tasks-axi` or `frontier-axi`:
   ```bash
   tasks-axi add "Fix DB leak in src/actions/bookings.ts violating bookings domain contract"
   ```
3. Run the slice through Edge Brigade to restore alignment with the contract.
