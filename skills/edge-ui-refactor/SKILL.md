---
name: edge-ui-refactor
profile: nextjs-drizzle-tailwind
description: Front-end UI refactoring manual for isolated subagents. Guides the safe extraction of repetitive Tailwind JSX markup into centralized primitives under src/components/ui/ with visual parity verification via chrome-devtools-axi.
---

# 🎨 /edge-ui-refactor — Frontend UI Primitive Consolidation Manual

> **Stack Profile:** `nextjs-drizzle-tailwind` — see [`profiles/nextjs-drizzle-tailwind/PLAYBOOK.md`](../../profiles/nextjs-drizzle-tailwind/PLAYBOOK.md).

This skill guides a bounded, single-purpose subagent through consolidating duplicate Tailwind JSX structures (modals, drawers, buttons, skeletons, cards) into centralized primitives under `src/components/ui/`.

---

## 🛑 Strict Guardrails & Safety Invariants

1. **Scope Boundary:** 
   - You may ONLY modify files in `src/components/` and `src/app/` (`.tsx` files).
   - **NEVER** modify or touch files in `src/actions/`, `src/core/`, `src/db/`, `src/lib/`, or root configs.
2. **Pure Tailwind CSS Standard:**
   - Do NOT introduce any external UI component libraries (no shadcn, Bootstrap, Radix, or Headless UI).
   - Use standard Tailwind utility classes with typed `variant` and `size` prop unions.
3. **Single Micro-Slice Principle:**
   - Focus exclusively on ONE approved primitive cluster per invocation (e.g. only `Modal`, only `Button`, or only `Skeleton`).
   - Keep total diff under 150 lines.
4. **Zero-Wrapper Left Behind (No Shallow Pass-Throughs):**
   - Whenever you consolidate or create a primitive (e.g. `Modal.tsx`), you MUST NOT leave a shallow wrapper behind (e.g. `ModalDialog.tsx`).
   - You MUST delete the legacy wrapper file completely (`git rm`) and migrate all call sites directly to the underlying primitive. Single-adapter pass-throughs violate Matt Pocock's Deletion Test.
5. **Max CC Non-Regression & Deterministic Metrics Gate:**
   - Artificial line-count contraction rules are retired; clean primitive extractions are evaluated by `Max CC Non-Regression` ($\text{CC}_{\text{after}} \le \max(\text{CC}_{\text{before}}, 10)$), `Zero-Wrapper`, `Domain Purity`, and `tools/gate.py --format json` metric deltas (`max_cc`, `dryer_clones`, `type_score`, `sloc` — missing analyzers report `null`, never `0`).
6. **Domain Schema vs Presentation State Purity:**
   - Presentation state (e.g. `isOpen`, `isClosed`, `activeTab`, local Tailwind animation classes) belongs to the UI component.
   - Domain semantics, canonical arrays (e.g. `CANONICAL_*`), table headers, business calculation parameters, and status lists MUST NOT be hardcoded inside JSX or frontend constants. They must come from the server/DB schema or domain dictionary.

---

## 🔄 The 7-Step Execution Protocol

```
1. Git Branch ──> 2. Baseline Shot ──> 3. Create Primitive ──> 4. Update Call Sites & Delete Wrappers
        │
        └───> 5. Compiler Check ──> 6. Parity Shot ──> 7. 4-Stage Edge Verification Gate & PR
```

### Step 1: Branch Isolation
Create and switch to an isolated feature branch:
```bash
git checkout -b refactor/ui-<slice-name>
```

### Step 2: Baseline Visual Capture
If the dev server is active (default: `http://localhost:3000`), capture a baseline screenshot of the target screen using `chrome-devtools-axi`:
```bash
chrome-devtools-axi open http://localhost:3000/<route>
chrome-devtools-axi screenshot <slice>-baseline.png
```
*(If `chrome-devtools-axi` is unavailable, fallback to `chrome-devtools-mcp` (`take_screenshot`) or the built-in `browser` subagent, or proceed to compiler checks).*

### Step 3: Centralize Primitive
Create or update the shared primitive in `src/components/ui/<Primitive>.tsx`:
- Export a clean TypeScript interface with `variant`, `size`, and slot props.
- Ensure keyboard accessibility (e.g. `Escape` key for modals/drawers) and backdrop dismissal.

### Step 4: Update Call Sites
Replace the repetitive raw JSX blocks across the target files identified in the UI Audit report with the new `<Primitive ... />`.

### Step 5: Deterministic Compiler Verification
Ensure zero type or build regressions:
```bash
# In project directory
npx tsc --noEmit
# Or run component tests if present
pnpm test:unit
```
If errors occur, fix them immediately. If unresolvable, run `git reset --hard HEAD` and report.

### Step 6: Deterministic Visual Parity Comparison
Compare the baseline and refactored screenshots deterministically using the built-in diff tool:
```bash
chrome-devtools-axi screenshot <slice>-refactored.png

# Fast, token-free matrix comparison with antialiasing tolerance:
uv run --with pillow python -m tools.ui_audit.diff_image <slice>-baseline.png <slice>-refactored.png --diff-out diff.png
```
- If mismatch $\le 0.15\%$: **PASS** (Zero vision tokens spent, visual parity guaranteed).
- If mismatch $> 0.15\%$: **FAIL** (Inspect the highlighted bounding box, adjust Tailwind classes, max 3 attempts).

### Step 7: Edge Verification Gate, 4-Seal `RefactorReceipt` & PR Delivery
Before submitting or creating a PR, run the deterministic Edge Verification Gate in JSON mode and seal the 4-seal `RefactorReceipt`:
```bash
python3 <plugin_root>/tools/gate.py <repo_path> --base HEAD~1 --track ui --format json
python3 <plugin_root>/tools/brigade/cli.py seal-refactor <repo_path> --base <integration_branch>  # e.g. development
```
All stages (`MigrationGate`, `Max CC Non-Regression`, `Mock Fallback`, `Type Escape`, `Dual-Theme & A11y`, `Zero-Wrapper`, `Domain Purity`, and `Hermetic Verification`) plus `RefactorReceiptVerifier` (`ExaminerReceipt PASS`, `examiner_cid != surgeon_cid`) must pass.
Then deliver via Brigade PR flow (`brigade finish-slice <repo> --pr`, followed by `brigade confirm-merge <repo>` once Two-Way Door auto-merge completes).
Report the resulting PR link or commit hash back to the parent agent.
