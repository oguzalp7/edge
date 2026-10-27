---
name: edge-audit
description: Unified deterministic codebase health, bloat, UI architecture, and test isolation auditor. Detects God files, cyclomatic complexity, deep nesting, shallow modules, orphan components, and test I/O leakage with actionable slicing recommendations.
---

# 🛡️ /edge-audit — Unified Codebase Health & Architecture Audit

This skill deterministically analyzes physical bloat (SLOC), cognitive complexity, module depth, UI component graphs, and unit test purity across your codebase.

---

## ⚡ Usage

### 1. Core Architectural Track (Default)
Audits SLOC bloat, cognitive complexity, function size, and test seams:
```bash
# Human-readable console report (colored tables)
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path>

# Agent / AXI format (Token-Oriented Object Notation)
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --format toon

# Save audit report to markdown
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> -o audit_report.md
```

### 2. UI Component & JSX Duplication Track
Audits Next.js/React TSX component DAG, orphan components, dead imports, and duplicate JSX clusters:
```bash
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track ui --format table
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track ui --format markdown -o ui_rfc.md
```

### 3. Unit Test Purity & Isolation Track
Audits TypeScript unit tests for physical database imports, DDL/DML leakage, uncontained seeds, and hardcoded collisions:
```bash
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track tests --format human
```

### 4. DRYER Structural AST Clones Track
Discovers structural AST duplication and equivalent clusters across TypeScript, TSX, JS, and Python:
```bash
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track clones --format human
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track clones --format markdown -o clones_report.md
```

### 5. Dead-Code Elimination Track
Audits unused files, unreferenced exports, and dead types via Knip with deterministic graph fallback:
```bash
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track dead-code --format human
```

### 6. Unified Whole-Repository Audit
Runs Core, UI, Test, Clone, and Dead-Code tracks simultaneously:
```bash
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py . --track all --format human
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py . --track all --format markdown -o full_audit.md
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py . --track all --format json -o full_audit.json
```

---

## 📊 Thresholds & Evaluation Rubric

- **Source Lines of Code (SLOC):**
  - `< 200`: 🟢 Clean (Optimal for human navigation & agent context)
  - `200 - 350`: 🟡 Attention (Approaching complexity boundaries, +12.0 risk)
  - `> 350`: 🔴 Hotspot (Candidate for vertical slicing, +25.0 risk)
  - `> 500`: 💀 Critical God File (Dilutes model attention, +45.0 risk)
- **Change Risk Anti-Patterns (CRAP) Scoring:**
  - Formula: $\text{CRAP}(m) = \text{CC}(m)^2 \times (1 - \text{cov}(m)/100)^3 + \text{CC}(m)$
  - `CRAP < 15.0`: 🟢 Well-tested function (suppresses `RULE-FAT-FUNCTION` warnings).
  - `15.0 <= CRAP < 30.0`: 🟡 Moderate risk.
  - `CRAP >= 30.0`: 🔴 Critical smell (`RULE-HIGH-CRAP`).
- **Nesting Level:** Indent levels $\ge 5$ require guard clauses and early returns (auto-detects 2-space vs 4-space formatting).
- **Module Depth (Ousterhout):** High SLOC files with $10+$ public exports are classified as **Shallow Leaky Modules**; internal mechanics should be hidden behind a unified facade.
- **Test Seams:** High-complexity files lacking companion test files are flagged as high risk (`MISSING_TEST_SEAM`).
- **UI Purity & Clean Separation:** TSX/JSX files mixing direct database queries or raw SQL operations are flagged as `UI_ACTION_MIXING`.
- **Health Score Calculation:** Overall codebase health score is computed using **SLOC-weighted risk** combined with a hotspot penalty to prevent God files from hiding behind clean barrel files.
