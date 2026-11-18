---
name: edge-ship
description: Milestone & Release Gate via no-mistakes. Validates committed changes on a feature/milestone branch through the no-mistakes pipeline (intent, rebase, review, test, document, lint, push, PR, CI) with PR targeting staging for automated Coolify deployment. Use when an epic, feature, or MVP milestone is completed.
user-invocable: true
---

# 🚀 /edge-ship — Milestone & Release Gate via no-mistakes

> *"Do not deploy individual micro-slices directly. Slices land fast-forward into local `development`. When a cohesive feature or MVP milestone is accomplished, trigger the `no-mistakes` verification gate to open a PR against `staging`, triggering remote Coolify redeployment upon merge."*

---

## 🎯 Purpose & Cadence

In the Edge architecture:
1. **Vertical Slices & Tickets**: Sliced by `edge-orchestrator`, executed in isolated `treehouse` worktrees, and fast-forward merged into local `development` via `edge-brigade`.
2. **Milestone / Epic Completion (`edge-ship`)**: Triggered **only** when a meaningful user journey, epic, or MVP milestone has landed on `development` (or a dedicated milestone branch).
3. **Target Integration Branch**: Strictly **`staging`**. Coolify is configured to monitor `staging` on GitHub and redeploy the staging container on push/merge.

---

## 🐧 Critical Execution Environment: WSL2 Protocol

> [!CRITICAL]
> All `no-mistakes` CLI commands MUST be executed inside **WSL2** (`/home/oguz/...`):
> ```bash
> wsl -e /bin/bash -lc "cd /home/oguz/<project> && no-mistakes axi run --base-branch staging --intent '<milestone_intent>' -y"
> ```

---

## 🔄 The no-mistakes Gate Pipeline

When invoked, `no-mistakes` validates code changes through a strict 9-phase deterministic gate:

1. **Intent Lock**: Pins the user's high-level goal and acceptance criteria (`--intent`).
2. **Rebase**: Hermetically rebases the branch onto `staging`.
3. **Automated Code Review**: Multi-agent review with automated remediation of actionable findings (`-y`).
4. **Test**: Executes test suite; verifies characterization and behavioral tests.
5. **Document**: Synchronizes bilingual docs, specs, and API contracts.
6. **Lint**: Runs project linter and formatting checks.
7. **Push**: Pushes validated branch to GitHub remote.
8. **PR Creation**: Drafts and opens a Pull Request targeting **`staging`**.
9. **CI Verification**: Verifies remote CI pipeline checks.

---

## ⚡ How to Ship a Milestone

### Step 1: Pre-Flight Check & Scope Inspection
Verify that all changes are committed and your working tree is clean:

```bash
# Check repository status and current branch in WSL
git status
git branch --show-current
```

If currently on `development`, create and checkout a release/milestone branch before initiating the gate:
```bash
git checkout -b release/<feature-milestone>
```

### Step 1.5: Specs-to-PR Bridge (`brigade prepare-ship`)
Before invoking `no-mistakes`, synthesize the deterministic Specs-to-PR payload to verify all QA proof receipts via `ProofVerifier`, classify One-way vs. Two-way Door risk, lock `--intent`, and generate the **Matt Pocock / Dex Horthy** PR body (`## Summary`, `## Evidence`, `## Merge Danger`):

```bash
# Generate PR body & validate proofs (exits 1 if any .edge/qa/proofs/*.json fails ProofVerifier)
python3 tools/brigade/cli.py prepare-ship . --base staging --format pr

# Or emit machine-readable JSON (contains intent, scenario_contract, pr_body, door_type, blast_radius)
python3 tools/brigade/cli.py prepare-ship . --base staging --format json --out .edge/ship-payload.json
```

### Step 2: Run no-mistakes Targeting Staging
Execute `no-mistakes axi run` with `--base-branch staging` using the locked `--intent` from `prepare-ship`:

```bash
no-mistakes axi run \
  --base-branch staging \
  --intent "Deliver <Milestone/Feature Name>: Complete vertical slice with repository extraction, visual parity, and characterization test coverage." \
  -y
```

> [!TIP]
> If you need to skip external CI checks during rapid staging previews:
> ```bash
> no-mistakes axi run --base-branch staging --skip ci --intent "<intent>" -y
> ```

### Step 3: Monitor Gate Status & Handle Approval Points
`no-mistakes axi` prints token-efficient [TOON](https://toonformat.dev) format.

If the gate pauses for a human decision or question:
```bash
# 1. View detailed status of active run
no-mistakes axi status

# 2. View step logs
no-mistakes axi logs --step <step_name>

# 3. Answer a question or approval gate
no-mistakes axi respond --answer "<decision>"

# 4. In case of fatal dead-end (between runs only)
no-mistakes axi abort
```

### Step 4: Outcome & Coolify Redeployment
Once `no-mistakes` outputs `disposition: completed`:
- A Pull Request targeting `staging` is open on GitHub.
- Once merged into `staging`, Coolify automatically pulls the updated branch, rebuilds the Docker container, and redeploys the staging environment.
