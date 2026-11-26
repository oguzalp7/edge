---
name: edge-ship
description: Brigade-Native Delivery Engine supporting Pure Core/TypeScript single_main (<integration_branch>=main) and Stack Profile two_tier topologies (Tier 1: 1 Spec = 1 PR -> <integration_branch>; Tier 2: Release PR <integration_branch> -> <staging_branch>). Synthesizes per-spec ship/<slug> branches, validates scoped ProofVerifier evidence, and creates lean PRs without external orchestrator wrappers.
user-invocable: true
---

# 🚀 /edge-ship — Brigade-Native Delivery Engine (`worktree -> <integration_branch> [-> <staging_branch>]`)

> *"Slices land fast-forward into `<integration_branch>` (`main` in Pure Core/`typescript` `single_main`; `development` in `nextjs-drizzle-tailwind` `two_tier`) after passing `VERIFY -> GATE -> [QA] -> REVIEW`. In `two_tier` profiles: **Tier 1 (`1 Spec = 1 PR -> <integration_branch>`)** opens isolated per-spec PRs, and **Tier 2 (`Release PR: <integration_branch> -> staging`)** promotes verified integration into staging."*

---

## 🛡️ Mandatory 4-Layer Stage Topology (`worktree -> integration -> staging -> production`)

`brigade prepare-ship` resolves stage branches from the active Stack Profile (`profiles/<id>/profile.json`) or `.edge/brigade.json` (`single_main`: `integration=main`; `two_tier` e.g. `nextjs-drizzle-tailwind`: `integration=development, staging=staging, production=production`):
- **Stage 1 (`worktree -> integration`):** Default `--base <integration_branch>` (if `--base` is omitted, `prepare-ship` diffs against the resolved `<integration_branch>`).
- **Stage 2 (`integration -> staging`, `two_tier` profiles):** Consolidated Release PR with `--require-smoke` (e.g., staging/Coolify deploy).
- **Stage 3 (`staging -> production`):** Production promotion after staging smoke clearance.
- **Stage 4 (Post-Release Smoke & Monitoring):** Continuous telemetry checks.
- **Per-Repo Customization & Manual Override:**
  - Configure `.edge/brigade.json` `"stage_branches"` (e.g., `{"integration": "main", "staging": "qa-stage"}`) or pass `--stage-branch key=val` on `prepare-ship`.
  - To bypass topology restrictions intentionally (e.g., urgent hotfix), pass `--allow-topology-override`.
  - Without `--allow-topology-override`, running `prepare-ship --base staging --split-branches` or `--base staging` from any slice branch (`feat/*`, `fix/*`, `refactor/*`, `hotfix/*`, `chore/*`, `ship/*`) is **blocked** (exit code `1`).

---

## 🎯 Purpose & PR Body Contract

- **Lean 2-Section PR Body & 1-Minute Briefing:** Emits concise `## Summary` starting with a **1-Minute Briefing** (*What changed*, *Why*, *Risk / Blast Radius*, *Verification* — 60-second scannable overview with verified counts) followed by code-only changed file count, `### Spec Expectations vs. Realization` diff + `AC`/`IC` criteria matrix, `### Architecture & Call-Stack Flow` Mermaid/call-stack blocks, `specs/INDEX.md`, `CONTEXT.md`, and `## Evidence` (spec link, Gate status, `### Examiner 3-Axis Seal` with collapsible repo-relative artifacts, `### Live QA Proof & Visual Evidence` with visited routes, collapsible E2E actions, formatted `db_crosscheck` JSON, and titled visual gallery).
- **Refactor Receipts & Door Brakes (`kind="refactor"`):** Discovers valid non-stale `.edge/receipts/refactor/<slug>.json` receipts bound to `(commit_sha, changed_files_hash)` under `target_repo`, builds `refactor(<slug>):` `SpecShipPlan` entries (avoiding `ship/<slug>` collisions via `ship/refactor-<slug>`), renders a `### Before/After Metric Delta` table under `## Summary` + `RefactorReceipt` / Gate / `Examiner 3-Axis Seal` under `## Evidence`, and enforces refactor One-Way Door brakes (exported public API removal/signature break, whole-segment auth/security paths excluding `sessionStorage.ts`/`authorName.tsx`, `> 15` files, or `> 500` diff lines). Two-Way Door PRs with `--auto` queued enter `AWAITING_MERGE` until `brigade confirm-merge` confirms `MERGED`, sets `status:done` via `tools/tracker`, and closes the child issue (soft-deprecating `tasks-axi done`). Passing `--issue <C> --parent-issue <P>` to `prepare-ship` caches `.edge/cache/issues/<C>.md` and emits `Closes #<C>` + `Parent Spec: #<P>` without auto-closing the parent.
- **Decoupled from `/edge-no-mistakes`:** Primary delivery uses native `brigade` + `gh` / `gh-axi` + CI. For optional external auditing, invoke `/edge-no-mistakes` separately.

---

## 🌐 Cross-OS Execution Environment

> [!IMPORTANT]
> Run `brigade` and `gh` shipping commands in the target repository's native runtime (`macos`, `linux`, `windows`, or `wsl`; prefix with `wsl --cd <linux_path>` only when targeting a WSL2 repository from a Windows host):
> ```bash
> brigade prepare-ship <repo_path> --base <integration_branch> --split-branches --format json
> ```

---

## ⚡ Tier 1: `1 Spec = 1 PR -> <integration_branch>` (Default)

### Step 1: Docs, Ontology & Drift Gate
Verify navigation index integrity, ontology consistency (`validate_ontology`), and living domain contracts before preparing PRs:
```bash
npm run check:navigation
python3 tools/drift/cli.py check . --ontology-only
python3 tools/drift/cli.py check .
```

### Step 2: Per-Spec Branch & PR Plan Synthesis (`--base <integration_branch>`)
Discover changed specs in `<integration_branch>..HEAD`, run scoped `ProofVerifier` validation, optionally publish QA screenshots onto an orphan evidence branch (`--publish-evidence`), and materialize isolated `ship/<spec-slug>` branches off `<integration_branch>`:
```bash
# Split all changed specs into isolated ship/<spec-slug> branches targeting the resolved integration branch
python3 tools/brigade/cli.py prepare-ship . --base <integration_branch> --split-branches --publish-evidence --evidence-branch edge-qa-evidence --format json --out .edge/ship-payload.json

# Or inspect / target a single spec slice (omitting --base defaults to the active profile integration branch)
python3 tools/brigade/cli.py prepare-ship . --base <integration_branch> --issue <child_num> --parent-issue <parent_num> --format pr
```

### Step 3: Push & Per-Spec PR Creation (`gh pr create --base <integration_branch>`)
For each `ship/<spec-slug>` branch in `spec_plans`:
```bash
git push -u origin ship/<spec-slug>
gh pr create --base <integration_branch> --head ship/<spec-slug> --title "<plan.pr_title>" --body "<plan.pr_body>"
```
*(Prefer `gh-axi` when available, falling back to `gh` CLI or `github-mcp-server`.)*

### Step 4: Remote CI Verification & Merge to `<integration_branch>`
```bash
gh pr checks <pr_number> --watch
```
Merge each verified PR into `<integration_branch>`.

---

## 🚢 Tier 2: `Release PR: <integration_branch> -> staging` (`two_tier` Profiles, e.g. `nextjs-drizzle-tailwind`)

Once slices are integrated and verified on `<integration_branch>` (e.g. `development`), run the Route Navigability & Console Smoke Gate before promoting `<integration_branch>` to `staging` as a single consolidated Release PR (never pass `--split-branches` here):

1. Ensure local `<integration_branch>` is checked out and synced:
   ```bash
   git checkout <integration_branch> && git pull
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
5. Push `<integration_branch>` (if needed) and open the consolidated Release PR:
   ```bash
   git push origin <integration_branch>
   gh pr create --base staging --head <integration_branch> --title "release: promote <integration_branch> to staging" --body-file .edge/release-body.md
   ```
6. Watch CI (`gh pr checks <pr_number> --watch`); merging into `staging` triggers profile-configured staging deployment (e.g. Coolify in `nextjs-drizzle-tailwind`).
