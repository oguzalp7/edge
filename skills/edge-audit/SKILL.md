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
Audits UI component DAG, orphan components, dead imports, and duplicate JSX clusters (active for UI-capable profiles such as `nextjs-drizzle-tailwind`):
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

### 6. TypeScript Type-System Discipline Track
Audits `.ts`/`.tsx` production files for type-system discipline (`RULE-TS-*` penalties + `BONUS-TS-DISCIPLINE` bonus, 0–100 SLOC-weighted score):
```bash
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track types --format human
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track types --format toon
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --track types --format markdown -o types_report.md
```

### 7. Unified Whole-Repository Audit
Runs Core, UI, Test, and TypeScript Type-System Discipline tracks simultaneously:
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
- **TypeScript Type-System Discipline (`--track types`, 0–100 Rubric):**
  - **Bands (SLOC-weighted repo score):** `85–100` 🟢 `STRICT` | `60–84` 🟡 `LOOSE` | `0–59` 🔴 `POROUS`.
  - **Penalties:**
    - `RULE-TS-EXPLICIT-ANY` (`-20p`, CRITICAL): `: any`, `<any>`, `as any`, `any[]`, `Array<any>`.
    - `RULE-TS-SUPPRESSION` (`-20p`, CRITICAL): `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`.
    - `RULE-TS-DOUBLE-CAST` (`-20p`, CRITICAL): `as unknown as <T>`.
    - `RULE-TS-UNSAFE-AS` (`-10p`, WARNING): `expr as <Type>` (excludes `as const`, `as any`, `as unknown as`, import/export aliases; recommends `satisfies` for object/array literals).
    - `RULE-TS-NON-NULL` (`-10p`, WARNING): Postfix non-null assertion `expr!`.
    - `RULE-TS-CONSOLE-LOG` (`-8p`, WARNING): `console.log(...)` in non-test production files.
    - `RULE-TS-RECORD-UNKNOWN` (`-8p`, WARNING): `Record<string, unknown>` inside `<core_paths>` (e.g. `src/core/` or `src/lib/`, allowed at perimeter).
    - `RULE-TS-SWITCH-EXHAUSTIVE` (`-8p`, WARNING): `switch` lacking a `default:` branch with a `: never` exhaustiveness binding.
    - `RULE-TS-OPTIONAL-BAG` (`-6p`, ADVISORY): Interface/object type mixing status booleans (`loading`, `isLoading`, `error`, `hasError`, `success`, `isSuccess`, `pending`, `isPending`) with $\ge 2$ optional fields.
    - `RULE-TS-POSITIONAL-ARGS` (`-5p`, ADVISORY): $\ge 4$ positional parameters or $\ge 2$ plain `*Id: string` parameters in one signature.
  - **Bonus:** `BONUS-TS-DISCIPLINE` (`+5p` once per file, capped at `100`) for `satisfies`, `readonly __brand`, `z.infer<...>`, or `: never` inside a `switch` `default:` block.
