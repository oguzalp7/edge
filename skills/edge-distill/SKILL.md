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

## 🔄 5-Step Operational Protocol

### Step 1: Zero-Token Harvest (Phase 1)
Execute the deterministic CLI harvester in WSL:
```bash
wsl python3 tools/distill/cli.py harvest --project <repo_path> --format toon
wsl python3 tools/distill/cli.py candidates list
```
- Optional flags: `--all-projects`, `--current <cid>`, `--reprocess`.
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
- **`--deep` Mode (3-Lens Parallel Fan-Out):**
  - Read each reference file via `read_file` and launch 3 parallel `Model: "flash"` workers with `Role: "Examiner"`:
    1. Lens 1 (`references/judgment-lens.md`): Downstream escapes across all Brigade stations + repeated user corrections (>= 2x).
    2. Lens 2 (`references/tooling-lens.md`): CLI friction, retry loops, and meat-proxy user handoffs.
    3. Lens 3 (`references/divergent-lens.md`): Contrarian no-op rule pruning and line budget compaction.
  - Collect synthesis findings via `send_message`.

---

### Step 3: Poteto 4-Level Routing & Stack Gating
For each proposed invariant:
1. Run `LexicalStackGate` classification:
   ```bash
   wsl python3 tools/distill/cli.py candidates record --rule "<rule>" --role <role> --project <repo_path>
   ```
2. **Classification Sieve:**
   - `REPO_LOCAL`: Contains stack, framework, or path tokens (Next.js, Drizzle, Tailwind, `.tsx`, `src/actions`). Routed to project overlay `.edge/stations/<role>.md` or `coding_standards.md`.
   - `PLUGIN_CANDIDATE`: Pure engineering discipline. Incubated in `.edge/stations/<role>.md` and registered in the candidate pool until validated across >= 2 distinct projects.
3. **Line Budget Ceiling Verification:**
   ```bash
   wsl python3 tools/distill/cli.py check-budget
   ```
   Strict physical line budgets enforced: `<= 60` lines for `agents/*.md` and `<= 40` lines for `.edge/stations/*.md`.

---

### Step 4: Captain Approval & Dual-Channel Delivery
Present a structured proposal table to the human captain:

| # | Channel | Target | Budget | Description | Evidence Citation |
|---|---------|--------|--------|-------------|-------------------|
| 1 | Channel A | .edge/stations/surgeon.md | 24/40 | Transaction boundary lock | TICK-101 guard failure |
| 2 | Channel A | agents/coder.md | 48/60 | Test Immutability Invariant | CAND-a1b2c3d4 (2 projects) |
| 3 | Channel B | tasks-axi | N/A | Add git branch checkout guard | 6x command failure |

**Delivery Channels:**
- **Channel A (Prose & Rubrics):** Apply approved diffs directly to `.edge/stations/<role>.md`, `coding_standards.md`, or plugin `agents/<role>.md`. When promoting a candidate, execute:
  ```bash
  wsl python3 tools/distill/cli.py promote --candidate <id>
  ```
  which appends to `agents/<role>.md` and cleans up duplicate local entries from `.edge/stations/<role>.md`.
- **Channel B (Structural Code & Tooling):** Create concrete `tasks-axi` tickets for mechanical checks (`gate.py` rules, AST linters, CLI wrappers). NEVER mutate production code directly in the primary working tree (Zero-Touch Primary Working Tree Invariant).

---

### Step 5: Watermark Seal & Scheduling
1. Mark analyzed sessions as processed:
   ```bash
   wsl python3 tools/distill/cli.py mark-processed --session <cid>
   ```
2. **Unattended Execution Mode (`/schedule`):**
   When running unattended on a recurring schedule (e.g. via `/schedule` weekly cron), do NOT block on `ask_question`. Instead, write the distilled proposals and evidence report to `.edge/distill/weekly-report.md` (or `<appDataDir>/edge_distill_weekly_report.md`) and notify the Captain without unapproved mutations.
