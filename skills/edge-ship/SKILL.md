---
name: edge-ship
description: Brigade-Native Two-Tier Delivery Engine (Tier 1: 1 Spec = 1 PR -> development; Tier 2: Release PR development -> staging). Synthesizes per-spec ship/<slug> branches, enforces development-first branch topology, validates scoped ProofVerifier evidence, and creates lean PRs without external orchestrator wrappers.
user-invocable: true
---

# 🚀 /edge-ship — Brigade-Native Two-Tier Delivery Engine (`worktree -> development -> staging`)

> *"Slices land fast-forward into local `development` after passing `VERIFY -> GATE -> [QA] -> REVIEW`. Shipping strictly follows a two-tier topology: **Tier 1 (`1 Spec = 1 PR -> development`)** opens isolated per-spec PRs into `development`, and **Tier 2 (`Release PR: development -> staging`)** promotes verified `development` into `staging` for Coolify deployment."*

---

## 🛡️ Mandatory 4-Layer Stage Topology (`worktree -> integration -> staging -> production`)

`brigade prepare-ship` models a 4-stage delivery chain (`DEFAULT_STAGE_BRANCHES`: `integration=development`, `staging=staging`, `production=production`):
- **Stage 1 (`worktree -> integration`):** Default `--base development` (if `--base` is omitted, `prepare-ship` diffs against `development` / `origin/development`).
- **Stage 2 (`integration -> staging`):** Consolidated Release PR with `--require-smoke` (Coolify deploy).
- **Stage 3 (`staging -> production`):** Production promotion after staging smoke clearance.
- **Stage 4 (Post-Release Smoke & Monitoring):** Continuous telemetry checks.
- **Per-Repo Customization & Manual Override:**
  - Configure `.edge/brigade.json` `"stage_branches"` (e.g., `{"integration": "main", "staging": "qa-stage"}`) or pass `--stage-branch key=val` on `prepare-ship`.
  - To bypass topology restrictions intentionally (e.g., urgent hotfix), pass `--allow-topology-override`.
  - Without `--allow-topology-override`, running `prepare-ship --base staging --split-branches` or `--base staging` from any slice branch (`feat/*`, `fix/*`, `refactor/*`, `hotfix/*`, `chore/*`, `ship/*`) is **blocked** (exit code `1`).

---

## 🎯 Purpose & PR Body Contract

- **Lean 2-Section PR Body:** Emits concise `## Summary` (code-only changed file count, `### Spec Expectations vs. Realization` diff + `AC`/`IC` criteria matrix, `### Architecture & Call-Stack Flow` Mermaid/call-stack blocks, `specs/INDEX.md`, `CONTEXT.md`) and `## Evidence` (spec link, Gate status, `### Examiner 3-Axis Seal` with collapsible repo-relative artifacts, `### Live QA Proof & Visual Evidence` with visited routes, collapsible E2E actions, formatted `db_crosscheck` JSON, and titled visual gallery).
- **Refactor Receipts & Door Brakes (`kind="refactor"`):** Discovers valid non-stale `.edge/receipts/refactor/<slug>.json` receipts bound to `(commit_sha, changed_files_hash)` under `target_repo`, builds `refactor(<slug>):` `SpecShipPlan` entries (avoiding `ship/<slug>` collisions via `ship/refactor-<slug>`), renders a `### Before/After Metric Delta` table under `## Summary` + `RefactorReceipt` / Gate / `Examiner 3-Axis Seal` under `## Evidence`, and enforces refactor One-Way Door brakes (exported public API removal/signature break, whole-segment auth/security paths excluding `sessionStorage.ts`/`authorName.tsx`, `> 15` files, or `> 500` diff lines). Two-Way Door PRs with `--auto` queued enter `AWAITING_MERGE` until `brigade confirm-merge` confirms `MERGED` and completes `tasks-axi done`.
- **Decoupled from `/edge-no-mistakes`:** Primary delivery uses native `brigade` + `gh` / `gh-axi` + CI. For optional external auditing, invoke `/edge-no-mistakes` separately.

---

## 🐧 Critical Execution Environment: WSL2 Protocol

> [!CRITICAL]
> All `brigade` and `gh` shipping commands MUST run inside **WSL2** (`/home/oguz/...`):
> ```bash
> wsl --cd /home/oguz/<project> python3 tools/brigade/cli.py prepare-ship . --base development --split-branches --format json
> ```

---

## ⚡ Tier 1: `1 Spec = 1 PR -> development` (Default)

### Step 1: Docs & Drift Gate
Verify navigation index integrity and living domain contracts before preparing PRs:
```bash
npm run check:navigation
python3 tools/drift/cli.py check .
```

### Step 2: Per-Spec Branch & PR Plan Synthesis (`--base development`)
Discover changed specs in `development..HEAD` (or `origin/development..development`), run scoped `ProofVerifier` validation, optionally publish QA screenshots onto an orphan evidence branch (`--publish-evidence`), and materialize isolated `ship/<spec-slug>` branches off `development`:
```bash
# Split all changed specs into isolated ship/<spec-slug> branches targeting development (default --base)
python3 tools/brigade/cli.py prepare-ship . --base development --split-branches --publish-evidence --evidence-branch edge-qa-evidence --format json --out .edge/ship-payload.json

# Or inspect / target a single spec slice (omitting --base also defaults to development)
python3 tools/brigade/cli.py prepare-ship . --base development --spec <spec-slug> --format pr
```

### Step 3: Push & Per-Spec PR Creation (`gh pr create --base development`)
For each `ship/<spec-slug>` branch in `spec_plans`:
```bash
git push -u origin ship/<spec-slug>
gh pr create --base development --head ship/<spec-slug> --title "<plan.pr_title>" --body "<plan.pr_body>"
```
*(Prefer `gh-axi` when available, falling back to `gh` CLI or `github-mcp-server`.)*

### Step 4: Remote CI Verification & Merge to `development`
```bash
gh pr checks <pr_number> --watch
```
Merge each verified PR into `development`.

---

## 🚢 Tier 2: `Release PR: development -> staging` (Coolify Promotion)

Once slices are integrated and verified on `development`, run the Route Navigability & Console Smoke Gate before promoting `development` to `staging` as a single consolidated Release PR (never pass `--split-branches` here):

1. Ensure local `development` is checked out and synced:
   ```bash
   git checkout development && git pull
   ```
2. Run the headless route smoke & perf telemetry scanner (`--format toon` default, configurable `--settle-budget-ms` and `--heap-budget-mb`):
   ```bash
   python3 tools/brigade/cli.py smoke-routes . --base-url http://localhost:3000 --format toon --settle-budget-ms 1500 --heap-budget-mb 80
   # With dynamic/auth overrides:
   python3 tools/brigade/cli.py smoke-routes . --base-url http://localhost:3000 --param id=42 --auth-cookie "session=..."
   ```
   - **Two-Tier Auto-Triage (`triage_smoke_failures`):**
     - **Tier A (`CRITICAL`):** Broken routes (`HTTP >= 400`, `console.error`, `pageerror`, auth redirect) or stuck spinners (`FAIL_STUCK`) upsert `TICK-SMOKE-<SLUG>` into `.edge/ledger/ui.json`.
     - **Tier B (`WARNING`):** Navigable slow/memory-heavy routes (`WARN_SLOW` / `WARN_MEMORY`) upsert `TICK-PERF-<SLUG>` (`ROUTE_PERF_SLOW_SETTLE`) into `.edge/ledger/ui.json`.
     - If Brigade is `IDLE`, `CRITICAL` `TICK-SMOKE-*` takes priority for `CycleState.TRIAGE`, falling back to the slowest `TICK-PERF-*` ticket.
3. Run an optional manual security audit or inspect `.edge/security/coverage-ledger.json` (`prepare-ship --base staging` also runs diff-scoped `security-audit` automatically):
   ```bash
   python3 tools/brigade/cli.py security-audit . --diff-only --base origin/staging --format toon
   ```
4. Generate the consolidated Staging Release PR payload with `--require-smoke` (`--base staging`, NO `--split-branches`; add `--stage-branch` / `--allow-topology-override` if overriding repository topology):
   ```bash
   python3 tools/brigade/cli.py prepare-ship . --base staging --require-smoke --format json --out .edge/release-payload.json
   # Or with custom stage mapping / manual bypass:
   python3 tools/brigade/cli.py prepare-ship . --base qa-stage --stage-branch staging=qa-stage --allow-topology-override --format json --out .edge/release-payload.json
   ```
   - `prepare-ship --base staging` automatically triggers diff-scoped `run_security_audit`, updates `.edge/security/coverage-ledger.json`, blocks with exit code `1` if confirmed vulnerabilities exist (triaging `TICK-SEC-*`), and embeds `### Included Specs & Realization` under `## Summary`, plus `### Route Navigability & Console Smoke Audit` and `### Security & ABAC Audit` under `## Evidence`.
5. Push `development` (if needed) and open the consolidated Release PR:
   ```bash
   git push origin development
   gh pr create --base staging --head development --title "release: promote development to staging" --body-file .edge/release-body.md
   ```
6. Watch CI (`gh pr checks <pr_number> --watch`); merging into `staging` triggers Coolify deployment.
