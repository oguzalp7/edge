---
name: edge-ship
description: Brigade-Native Two-Tier Delivery Engine (Tier 1: 1 Spec = 1 PR -> development; Tier 2: Release PR development -> staging). Synthesizes per-spec ship/<slug> branches, enforces development-first branch topology, validates scoped ProofVerifier evidence, and creates lean PRs without external orchestrator wrappers.
user-invocable: true
---

# 🚀 /edge-ship — Brigade-Native Two-Tier Delivery Engine (`worktree -> development -> staging`)

> *"Slices land fast-forward into local `development` after passing `VERIFY -> GATE -> [QA] -> REVIEW`. Shipping strictly follows a two-tier topology: **Tier 1 (`1 Spec = 1 PR -> development`)** opens isolated per-spec PRs into `development`, and **Tier 2 (`Release PR: development -> staging`)** promotes verified `development` into `staging` for Coolify deployment."*

---

## 🛡️ Mandatory Branch Topology (`validate_branch_topology`)

`brigade prepare-ship` enforces **`worktree -> development -> staging`** via `validate_branch_topology`:
- **Default Base Branch:** `--base development` (if `--base` is omitted, `prepare-ship` diffs against `development` / `origin/development`).
- **Blocked Topology Violations (exit code `1`):**
  - Running `prepare-ship --base staging --split-branches` is **FORBIDDEN** (`ship/<slug>` branches must NEVER bypass `development`).
  - Running `prepare-ship --base staging` from any slice branch (`feat/*`, `fix/*`, `refactor/*`, `hotfix/*`, `chore/*`, `ship/*`) is **FORBIDDEN**.
- **Smart Remote Base Resolution (`_resolve_base_ref`):**
  - When `HEAD == development` and `--base development`, diffs `origin/development..development` (falling back to local `development` if no remote).
  - When `--base staging` from `development`, anchors on `origin/staging` (falling back to local `staging` if no remote).

---

## 🎯 Purpose & PR Body Contract

- **Lean 2-Section PR Body:** Emits concise `## Summary` (code-only changed file count, `### Spec Expectations vs. Realization` diff + `AC`/`IC` criteria matrix, `### Architecture & Call-Stack Flow` Mermaid/call-stack blocks, `specs/INDEX.md`, `CONTEXT.md`) and `## Evidence` (spec link, Gate status, `### Examiner 3-Axis Seal` with collapsible repo-relative artifacts, `### Live QA Proof & Visual Evidence` with visited routes, collapsible E2E actions, formatted `db_crosscheck` JSON, and titled visual gallery).
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
2. Run the headless route smoke scanner across all discovered routes (`--param` overrides dynamic segments like `[id]`; `--auth-cookie` authenticates protected routes):
   ```bash
   python3 tools/brigade/cli.py smoke-routes . --base-url http://localhost:3000
   # With dynamic/auth overrides:
   python3 tools/brigade/cli.py smoke-routes . --base-url http://localhost:3000 --param id=42 --auth-cookie "session=..."
   ```
   - Any non-navigable route (`HTTP >= 400`, `console.error`, uncaught `pageerror`, or unexpected auth redirect) automatically upserts a `CRITICAL` `TICK-SMOKE-<SLUG>` ticket into `.edge/ledger/ui.json` and transitions an `IDLE` Brigade into `CycleState.TRIAGE`.
3. Generate the consolidated Staging Release PR payload with `--require-smoke` (`--base staging`, NO `--split-branches`):
   ```bash
   python3 tools/brigade/cli.py prepare-ship . --base staging --require-smoke --format json --out .edge/release-payload.json
   ```
   The consolidated body includes `### Included Specs & Realization` under `## Summary` and `### Route Navigability & Console Smoke Audit` under `## Evidence`.
4. Push `development` (if needed) and open the consolidated Release PR:
   ```bash
   git push origin development
   gh pr create --base staging --head development --title "release: promote development to staging" --body-file .edge/release-body.md
   ```
5. Watch CI (`gh pr checks <pr_number> --watch`); merging into `staging` triggers Coolify deployment.
