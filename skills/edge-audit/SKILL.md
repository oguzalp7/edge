---
name: edge-audit
description: Deterministic codebase health, bloat, and module depth auditor. Detects God files, excessive cyclomatic complexity, deep nesting, and shallow modules with actionable slicing recommendations.
---

# 🛡️ /edge-audit — Codebase Health & Bloat Audit

This skill deterministically analyzes physical bloat (SLOC), cognitive complexity, and module depth across your codebase.

---

## ⚡ Usage

To audit a target directory or your current workspace:

```bash
# Human-readable console report (colored tables)
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path>

# Agent / AXI format (Token-Oriented Object Notation)
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> --format toon

# Save audit report to markdown
uv run python ~/.gemini/config/plugins/edge/tools/audit/cli.py <target-path> -o audit_report.md
```

---

## 📊 Thresholds & Evaluation Rubric

- **Source Lines of Code (SLOC):**
  - `< 200`: 🟢 Clean (Optimal for human navigation & agent context)
  - `200 - 350`: 🟡 Attention (Approaching complexity boundaries)
  - `> 350`: 🔴 Hotspot (Candidate for vertical slicing)
  - `> 500`: 💀 Critical God File (Severely dilutes model attention & induces hallucinations)
- **Nesting Level:** Indent levels $\ge 5$ require guard clauses and early returns.
- **Module Depth (Ousterhout):** High SLOC files with $10+$ public exports are classified as **Shallow Leaky Modules**; internal mechanics should be hidden behind a unified facade.
- **Test Seams:** High-complexity files lacking companion test files are flagged as high risk for refactoring.
