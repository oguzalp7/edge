---
name: edge-distill
description: Self-Improving Software Factory Engine. Converts execution friction, guard failures, and human corrections from Antigravity transcripts and FlightRecorder into permanent engineering improvements via zero-token harvesting, Cold Goldfish synthesis, and dual-channel delivery.
suggested_skills:
  - edge-orchestrator
  - edge-brigade
---

# 🏛️ /edge-distill — Self-Improving Software Factory Engine

> *"Do not force generic prompt bloat onto autonomous coding agents. Transform raw execution friction, test failures, and human corrections into verified, permanent engineering invariants."*

`edge-distill` is an autonomous two-phase engineering feedback engine:
1. **Zero-Token Passive Harvest (Phase 1):** Deterministic Python harvester scanning Antigravity session transcripts and FlightRecorder without LLM token expenditure.
2. **Cold Goldfish Synthesis (Phase 2):** Ephemeral, low-cost subagent (`Model: "flash"`, `Role: "Examiner"`) analyzing the extracted `FrictionDigest` under strict prompt-injection protection.

---

## 🌐 Operational Modes: PROJECT_MODE vs FACTORY_MODE

- **`PROJECT_MODE` (Application Target):**
  - Triggered automatically when targeting an application repo (`target_repo != plugin_root`) or explicitly via `--mode project`.
  - Channel A updates are strictly restricted to application-local files: `.edge/stations/<role>.md` (budget `<= 40` lines) or `coding_standards.md`.
  - **Strict Mutation Prohibition:** Never write to `edge` plugin files (`agents/*.md`, `skills/**`) or file plugin issues in the application repo.
  - Harness friction, WSL relay errors, and station escapes are excluded from the application digest and silently queued into `edge_factory_inbox.json`.
- **`FACTORY_MODE` (Edge Plugin Self-Improvement):**
  - Triggered when targeting the `edge` plugin itself (`target_repo == plugin_root`) or explicitly via `--mode factory`.
  - Drains pending harness signals from `edge_factory_inbox.json` alongside multi-project candidate rules.
  - Channel A modifies plugin agent rubrics `agents/<role>.md` (budget `<= 60` lines) and `skills/**`.
  - All improvements must pass verification gates (`python3 tools/distill/cli.py check-budget .` and pytest suite) and be sealed in an `atomic git commit`: `chore(distill): apply factory improvements`.

---

## 🔄 5-Step Operational Protocol

### Step 1: Zero-Token Harvest (Phase 1)
Execute the deterministic CLI harvester in the active shell (use `wsl --cd <linux_path>` only when targeting a WSL2 repo from Windows):
```bash
python3 tools/distill/cli.py harvest --project <repo_path> --format toon --mode auto
python3 tools/distill/cli.py candidates list
```
- Optional flags: `--mode {auto,project,factory}`, `--all-projects`, `--current <cid>`, `--reprocess`.
- **Zero-Friction Exit Condition:** If `harvest` finds zero unharvested sessions and `candidates list` has no pending promotions, print:
  `"✨ Harvester clean: No unprocessed sessions or pending promotions found. Exiting with 0 tokens spent."`
  and terminate immediately without spawning any subagents.

---

### Step 2: Cold Goldfish Synthesis (Phase 2)
If unprocessed sessions or ready candidates exist, spawn an isolated subagent with zero prior conversational baggage:
- **Default Mode (Single Synthesizer):**
  - Use `read_file` to load `skills/edge-distill/references/synthesizer.md`.
  - Dispatch via `invoke_subagent`:
    - `TypeName: "self"`
    - `Model: "flash"`
    - `Role: "Examiner"`
    - Embed the TOON `FrictionDigest` inside `<untrusted_telemetry_digest>...</untrusted_telemetry_digest>`.
- **`--deep` Mode (4-Lens Parallel Fan-Out):**
  - Read each reference file via `read_file` and launch parallel `Model: "flash"` workers with `Role: "Examiner"`:
    1. Lens 1 (`references/judgment-lens.md`): Downstream escapes across all Brigade stations + repeated user corrections (>= 2x).
    2. Lens 2 (`references/tooling-lens.md`): CLI friction, retry loops, meat-proxy handoffs, `Guardrail Gaps`, and `TOKEN_BLOAT`.
    3. Lens 3 (`references/divergent-lens.md`): Contrarian no-op rule pruning using `Rule Inventory` citations and line budget compaction.
    4. Lens 4 (`references/navigation-lens.md`): `Navigation & Tool Economy` signals (`EXPLORATION_BURST`, `REDUNDANT_READ`, `EMPTY_SEARCH_CHAIN`) into `docs/<domain>/DOMAIN.md` Context Pointers.
  - Collect synthesis findings via `send_message`.

---

### Step 3: Poteto 4-Level Routing & Stack Gating
For each proposed invariant:
1. Run `LexicalStackGate` classification:
   ```bash
   python3 tools/distill/cli.py candidates record --rule "<rule>" --role <role> --project <repo_path>
   ```
2. **Classification Sieve:**
   - `REPO_LOCAL`: Contains stack, framework, or path tokens defined by Stack Profiles (e.g., `profiles/nextjs-drizzle-tailwind/`). Routed to project overlay `.edge/stations/<role>.md` or `coding_standards.md`.
   - `PLUGIN_CANDIDATE`: Pure engineering discipline. Incubated in `.edge/stations/<role>.md` and registered in the candidate pool until validated across >= 2 distinct projects.
3. **Line Budget Ceiling Verification:**
   ```bash
   python3 tools/distill/cli.py check-budget
   ```
   Strict physical line budgets enforced: `<= 60` lines for `agents/*.md` and `<= 40` lines for `.edge/stations/*.md`.

---

### Step 4: Captain Approval & Dual-Channel Delivery
Present each proposal to the human captain as a **4-Line Commander Decision Card** (if any line is unclear or lacks concrete evidence, mark **`REJECT`** by default):

- **What failed:** `<concrete telemetry failure or escape + evidence citation>`
- **1-line rule diff:** `<exact Channel A line/budget diff or Channel B frontier-axi/tasks-axi delta>`
- **Real risk if rejected:** `<specific defect class that recurs without this change>`
- **Possible conflict:** `<overlapping rule/domain invariant, or "None"; unclear -> REJECT>`

**Delivery Channels:**
- **Channel A (Prose, Rubrics & Context Pointers):** Apply approved diffs directly to `.edge/stations/<role>.md`, `coding_standards.md`, `docs/<domain>/DOMAIN.md`, or plugin `agents/<role>.md`. When promoting a candidate, execute:
  ```bash
  python3 tools/distill/cli.py promote --candidate <id>
  ```
  which appends to `agents/<role>.md` and cleans up duplicate local entries from `.edge/stations/<role>.md`.
- **Channel B (Structural Code & Tooling — Frontier-First Parking Gate):**
  Per AXI Rule 1.A, structural tooling proposals default to the active repo's **`frontier-axi`** parking lot:
  ```bash
  frontier-axi add <id> "<title>" --body "<evidence and open questions>"
  ```
  Direct `tasks-axi` ticketing occurs **ONLY** upon explicit Captain selection/escalation during review. NEVER mutate production code directly in the primary working tree (Zero-Touch Primary Working Tree Invariant).

---

### Step 5: Watermark Seal & Scheduling
1. Mark analyzed sessions as processed:
   - In `PROJECT_MODE`:
     ```bash
     python3 tools/distill/cli.py mark-processed --session <cid> --mode project
     ```
   - In `FACTORY_MODE`:
     ```bash
     python3 tools/distill/cli.py mark-processed --session <cid> --mode factory --clear-factory-inbox
     ```
2. **Unattended Execution Mode (`/schedule`):**
   When running unattended on a recurring schedule (e.g. via `/schedule` weekly cron), do NOT block on `ask_question`. Instead, write the distilled proposals and evidence report to `.edge/distill/weekly-report.md` (or `<appDataDir>/edge_distill_weekly_report.md`) and notify the Captain without unapproved mutations.
