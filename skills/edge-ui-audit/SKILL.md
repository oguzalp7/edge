---
name: edge-ui-audit
description: Deterministic UI component graph analyzer, orphan component detector, and pure Tailwind JSX structural duplicate clusterer. Recommends centralized UI primitives and guides visual parity verification via chrome-devtools-axi.
---

# 🎨 /edge-ui-audit — Frontend UI Component & Duplicate JSX Audit

This skill deterministically audits front-end React/Next.js codebases (`src/app` and `src/components`), specifically tailored for **pure Tailwind CSS** architectures without external component library bloat.

---

## ⚡ Usage

```bash
# Human-readable console summary
uv run python ~/.gemini/config/plugins/edge/tools/ui_audit/cli.py <target-path>

# Detailed Markdown RFC for human review & proposal inspection
uv run python ~/.gemini/config/plugins/edge/tools/ui_audit/cli.py <target-path> --format markdown --out ui-audit-report.md

# Agent / AXI format (Token-Oriented Object Notation)
uv run python ~/.gemini/config/plugins/edge/tools/ui_audit/cli.py <target-path> --format toon
```

---

## 🔍 Core Capabilities

1. **Component Reference DAG & Orphan Detection:**
   - Maps all exports and imports across `src/components/` and `src/app/`.
   - Identifies **Orphan Components**: files under `src/components/` with zero ingress references from any route or component (safe candidates for pruning or review).
   - Identifies **Dead Symbol Imports**: imported icons or helper components never rendered or referenced in the file body.

2. **Tailwind JSX Structural Fingerprinting:**
   - Normalizes and tokenizes JSX class attributes.
   - Detects recurring markup patterns across components:
     - `modal_overlay` / `modal_container` $\rightarrow$ candidates for `src/components/ui/Modal.tsx`
     - `drawer` $\rightarrow$ candidates for `src/components/ui/Drawer.tsx`
     - `skeleton` $\rightarrow$ candidates for `src/components/ui/Skeleton.tsx`
     - `button` $\rightarrow$ candidates for `src/components/ui/Button.tsx` (`variant` props)
     - `card` $\rightarrow$ candidates for `src/components/ui/Card.tsx`
     - `alert_banner` $\rightarrow$ candidates for `src/components/ui/Alert.tsx`
     - `table_container` $\rightarrow$ candidates for `src/components/ui/TableWrapper.tsx`

3. **Visual Parity Verification Protocol:**
   - **Primary Engine:** `chrome-devtools-axi` (CLI at `/usr/local/bin/chrome-devtools-axi`) for fast, token-efficient screenshot capture.
   - **Fallback Engine:** `chrome-devtools-mcp` (`take_screenshot`, `navigate_page`).
   - Captures baseline and refactored screenshots to verify styling parity during consolidation (max 3 loops).
