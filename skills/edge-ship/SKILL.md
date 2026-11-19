---
name: edge-ship
description: Brigade-Native "1 Spec = 1 PR" Delivery Engine targeting staging. Synthesizes per-spec ship/<slug> branches, scoped ProofVerifier evidence, lean Pocock/Show-Me PR bodies, GitHub PR creation, and CI watch without external orchestrator wrappers.
user-invocable: true
---

# 🚀 /edge-ship — Brigade-Native Per-Spec Delivery Engine (`1 Spec = 1 PR`)

> *"Slices land fast-forward into local `development` after passing `VERIFY -> GATE -> [QA] -> REVIEW`. When shipping from `development` to `staging`, each changed spec gets its own isolated `ship/<spec-slug>` PR backed by scoped `ProofVerifier` receipts and remote CI checks."*

---

## 🎯 Purpose & Architecture

- **1 Spec = 1 PR:** Never lump unrelated completed slices into one monolithic PR. `brigade prepare-ship --split-branches` discovers each spec touched in `staging..HEAD`, validates only its scoped `.edge/qa/proofs/<spec-slug>.json` receipts, and creates `ship/<spec-slug>` off `staging`.
- **Lean 2-Section PR Body:** Emits concise `## Summary` (branch/spec scope, Mermaid architecture digest, `specs/INDEX.md`, `CONTEXT.md`) and `## Evidence` (spec link, Gate status, Examiner seal, SHA-256 verified QA screenshots, `db_crosscheck`).
- **Target Integration Branch:** Strictly **`staging`** (triggers Coolify redeployment upon PR merge).
- **Decoupled from `/edge-no-mistakes`:** Primary delivery uses native `brigade` + `gh` / `gh-axi` + CI. For optional external auditing, invoke `/edge-no-mistakes` separately.

---

## 🐧 Critical Execution Environment: WSL2 Protocol

> [!CRITICAL]
> All `brigade` and `gh` shipping commands MUST run inside **WSL2** (`/home/oguz/...`):
> ```bash
> wsl --cd /home/oguz/<project> python3 tools/brigade/cli.py prepare-ship . --base staging --split-branches --format json
> ```

---

## ⚡ 4-Step Brigade-Native Shipping Pipeline

### Step 1: Docs & Drift Gate
Verify navigation index integrity and living domain contracts before preparing PRs:
```bash
npm run check:navigation
python3 tools/drift/cli.py check .
```

### Step 2: Per-Spec Branch & PR Plan Synthesis (`brigade prepare-ship`)
Discover changed specs in `staging..HEAD`, run scoped `ProofVerifier` validation (ignoring stale historical proofs), and materialize isolated `ship/<spec-slug>` branches:
```bash
# Split all changed specs into isolated ship/<spec-slug> branches and emit JSON plans
python3 tools/brigade/cli.py prepare-ship . --base staging --split-branches --format json --out .edge/ship-payload.json

# Or inspect / target a single spec slice
python3 tools/brigade/cli.py prepare-ship . --base staging --spec <spec-slug> --format pr
```

### Step 3: Push & Per-Spec PR Creation (`gh pr create --base staging`)
For each `ship/<spec-slug>` branch in `spec_plans`:
```bash
git push -u origin ship/<spec-slug>
gh pr create --base staging --head ship/<spec-slug> --title "<plan.pr_title>" --body "<plan.pr_body>"
```
*(Prefer `gh-axi` when available, falling back to `gh` CLI or `github-mcp-server`.)*

### Step 4: Remote CI Verification (`gh pr checks`)
Monitor remote CI status on each opened PR:
```bash
gh pr checks <pr_number> --watch
```
Once CI is green and the PR merges into `staging`, Coolify automatically redeploys the staging environment.
