---
name: edge-brigade
description: Michelin Station (Brigade de Cuisine) deterministic State Machine Engine. Orchestrates persistent and ephemeral station workers (Spec Writer, Spec Critic, Researcher, Seam Architect, Coder, Surgeon, Examiner, QA Engineer) with hardcoded state transitions governed by OS exit codes and data invariants rather than LLM self-assessment.
---

# 🏛️ /edge-brigade — Michelin Station & Deterministic State Machine Engine

> *"Own your control flow. Small, focused agents. Stateless reducers with deterministic transition gates. The model must never decide its own transitions; transitions are governed 100% by OS process exit codes."*
> — **Dexter Horthy (12-Factor Agents)** & **Lauren Tan / Poteto (Brigade de Cuisine)**

`edge-brigade` transforms autonomous refactoring from a stochastic generalist LLM loop into a hardcoded **Finite State Machine (FSM)**.

---

## 🍽️ The Michelin Brigade Metaphor (Sabit İstasyon / Sabit Memur)

Instead of spawning disposable generalist agents that try to do everything and evaluate their own success, the system assigns long-lived station workers with persistent `conversation_id`s in Antigravity:

```
  +------------------------------------------------------------------------+
  |            DETERMINISTIC FSM DELIVERY (brigade finish-slice)           |
  +-------------------+--------------------------------+-------------------+
                      |                                |
       [TRACK: FEATURE]                                [TRACK: REFACTOR]
       +--------------+---------------+ +--------------+---------------+
       | SPEC WRITER (lavish-axi Gate)| |   SURGEON (Chef de Partie)    |
       | SPEC CRITIC (Cross-Provider) | |   Architecture & Decoupling   |
       | RED_TEST (Upfront Worktree)  | |   (Contraction Decoupled)     |
       | SEAM ARCHITECT (Red Tests)   | |                               |
       | CODER (Turns Red to Green)   | |                               |
       +--------------+---------------+ +--------------+---------------+
                      |                                |
                      +----------------+---------------+
                                       |
                                       v
       +---------------------------------------------------------------+
       |                 GATE (tools/gate.py + diff_image.py)          |
       |       Static/CC/Drift Gate & UI Visual Parity (<= 0.15%)      |
       +-------------------------------+-------------------------------+
                                       |
                                       v
       +---------------------------------------------------------------+
       |           [OPTIONAL] QA_ENGINEER (Sommelier + ProofVerifier)  |
       |  E2E Browser Delegation, SHA-256 Shots & DB Cross-Check Proof |
       +-------------------------------+-------------------------------+
                                       |
                                       v
       +---------------------------------------------------------------+
       |                   EXAMINER (Sous / Maitre d')                 |
       |  3-Axis Evidence-First Review (Standards, Spec, Evidence)     |
       |              + Mandatory `brigade seal-review`                |
       +-------------------------------+-------------------------------+
                                       |
                                       v
       +---------------------------------------------------------------+
       |             Deterministic Merge (brigade finish-slice)        |
       |     Spec Archival, /edge-drift Audit & `brigade prepare-ship` |
       +---------------------------------------------------------------+
```

### The 8 Brigade Stations (Kadro Yapılanması):
1. **SPEC_WRITER (`spec_writer`)**:
   - **Role:** Ubiquitous language translator & N-Spec slicer.
   - **Constraint:** Condenses user story into 3-4 plain English sentences. Enforces Pocock/Dexter Horthy vertical slice completeness (DB -> Core -> API -> UI). **Visual Approval Gate (`lavish-axi`):** If UI is touched, MUST author interactive HTML in `.lavish/<feature>.html` and obtain user approval before coding.
2. **SPEC_CRITIC (`spec_critic`)**:
   - **Role:** Cross-provider zero-context specification critic & anti-debt auditor.
   - **Execution:** Runs via `brigade critique-spec <repo> --spec <path>` using `claude-opus-5-5-high` (automatic quota fallback to `gemini-3.8-flash-high`) and writes `.edge/specs/<stem>-critique.md`.
   - **Constraint:** Advisory gate (< 400 words plain English); surfaces reusable utilities and unstated edge cases without hard-locking FSM.
3. **RESEARCHER (`researcher`)**:
   - **Role:** Deep codebase exploration, AST tracing, external documentation verification, and root cause analysis.
   - **Constraint:** Zero production code mutation; delivers evidence-backed seam recommendations. Strictly read-only.
4. **SEAM_ARCHITECT (`seam_architect`)**:
   - **Role:** Michael Feathers seam architect & contract author.
   - **Constraint:** Declares TypeScript interfaces and writes **RED Unit/Contract Tests** that initially fail (TDD anchor) inside the leased Treehouse worktree.
5. **CODER (`coder`)**:
   - **Role:** Production code worker.
   - **Constraint:** Turns red tests GREEN with minimal, clean code inside the leased worktree. **Test Immutability:** Cannot modify or loosen test assertions.
6. **SURGEON (`surgeon` / Chef de Partie)**:
   - **Role:** Refactor & structural cleanup specialist.
   - **Constraint:** Decouples bloated controllers and extracts domain repositories in an isolated worktree. Bound by the **MigrationGate Invariant** (never mutates schema or migrations).
7. **EXAMINER (`examiner` / Sous Chef & Maître d')**:
   - **Role:** Evidence-first 3-axis review (`standards`, `spec`, `evidence`) inspecting diffs alongside `gate.py`, UI `diff_image.py` pixel diffs, QA proof receipts, screenshots, and `db_crosscheck` in a single concise pass (< 350 words).
   - **Constraint:** Strictly read-only. Must seal verdict via `brigade seal-review <repo> --verdict PASS|FAIL --summary "..."` before `REVIEW -> STAGING` can pass; skips deterministic checks already enforced by `gate.py`.
8. **QA_ENGINEER (`qa_engineer` / Sommelier)**:
   - **Role:** End-to-end browser verification, visual quality assurance, and user journey testing.
   - **Protocol:** Receives translated user scenarios mapped to project ubiquitous domain vocabulary by the Orchestrator. Delegates physical browser interactions to the built-in `browser` subagent (`TypeName: "browser"`, `Model: "flash"`). Stages Lavish references to `<Artifact Directory>/browser_sandbox/references/`. Enforces state persistence via DOM reload and backend DB/state cross-checks (`run_command`). Synthesizes `ProofVerifier`-compliant Behavioral Proof Receipt (`.edge/qa/proofs/<slug>.json` with unique-SHA-256 screenshots, non-auth URLs, `host_facts_verified: true`, and `db_crosscheck`) before advancing to `REVIEW` (`EXAMINER`).
   - **Constraint:** Strictly zero production code mutation (`<source_roots>`, e.g., `src/**`, `app/**`, `lib/**`, `db/**`). Documents defects with reproduction steps, network payloads, console errors, and screenshots. Parks non-blocking UX issues via `qa-inspect --frontier` into `tools/tracker` (`type:frontier`, `track:ui`; `frontier-axi` soft-deprecated).

### Station Memory Models: Elephant vs. Goldfish
* 🐘 **Persistent Elephant Stations (`PERSISTENT_ELEPHANT_ROLES`):**  
  `SPEC_WRITER`, `RESEARCHER`, `SEAM_ARCHITECT`, `CODER`, `SURGEON`, `QA_ENGINEER`.  
  Retain domain context and are reused via `send_message` while in the **GREEN zone** (`< 45k` tokens, `GREEN_HEAT_THRESHOLD = 45,000`).
* 🐟 **Ephemeral Goldfish Stations (`EPHEMERAL_GOLDFISH_ROLES`):**  
  `EXAMINER` and `SPEC_CRITIC`.  
  Spawned fresh with zero conversational history (`invoke_subagent`) on every review pass to eliminate confirmation bias; `orchestrator_guard.py` permits fresh spawns even in GREEN heat and marks prior instances `ROTATED`.
* 🧬 **Strategic Domain Context Forking (`fork` Cherry-Picking):**
  - **`EXAMINER`:** Fork from `spec_writer` (`fork: "spec_writer"`) or `researcher` (`fork: "researcher"`) to inherit domain vocabulary and specification contracts while remaining 100% unbiased toward implementation diffs. NEVER fork from `coder` or `surgeon`.
  - **`SPEC_WRITER`:** N-Spec / variant cloning.
  - **`RESEARCHER`:** Multi-hypothesis / warm handoff for deep investigations.
* ⚡ **Configurable Station Model (`model: str = "flash"` SSOT):**  
  Stations default to `model: "flash"` across registration, FSM storage (`.edge/brigade.json`), and prompt dispatch. Explicit model pinning is supported via `brigade register --model <model>`.
* 🐝 **Swarm vs. Brigade Guidance:**  
  For comparing deterministic Brigade state machines with native horizontal swarms and lightweight guardrails, refer to [**`rules/playbooks/swarm-vs-brigade.md`**](file:///C:/Users/oguz_/.gemini/config/plugins/edge/rules/playbooks/swarm-vs-brigade.md).

---

## 🔄 State Machine Lifecycle & Deterministic Guards

Transitions are **stateless reducers** governed purely by process exit codes and hard data assertions:

```
                  [ TRACK: FEATURE ]                     [ TRACK: REFACTOR ]
                         IDLE                                   IDLE
                          │ (start-slice --track feature)        │ (triage from core ledger)
                          ▼                                      ▼
                      RED_TEST                                TRIAGE
                          │ (SEAM_ARCHITECT red tests            │ (validate target file
                          │  guard_red_test: exit != 0)          │  & worktree lease)
                          ▼                                      ▼
                       SURGERY                                SURGERY
                          │ (CODER green code                    │ (SURGEON refactors,
                          │  inside leased worktree)             │  target_contraction < 0)
                          └───────────────────┬──────────────────┘
                                              │
                                              ▼
                                           VERIFY
                                              │ (guard_verify_to_gate: tests exit==0, typecheck exit==0)
                                              ▼
                                            GATE
                                              │ (guard_gate_to_next: gate.py==0 + ui diff_image<=0.15%)
                                              ├──────────────────────────────┐
                                              │ should_run_qa()==True        │ should_run_qa()==False
                                              ▼                              │
                                             QA  (ProofVerifier + DB check)  │
                                              │                              │
                                              ├──[CRITICAL]──► POLISH        │
                                              └──────────────────────────────┤
                                                                             ▼
                                           REVIEW <---[POLISH -> GATE -> ...]┘
                                              │ (EXAMINER: 3-axis + `brigade seal-review`)
                                              ├──[CRITICAL or FAIL]──► POLISH (re-enters GATE)
                                              ▼ [0 CRITICAL & ExaminerReceipt PASS]
                                           STAGING
                                              │ (guard_staging: git merge --ff-only into <integration_branch>,
                                              │  archives .edge/specs/<slice>.md to .edge/archive/specs/,
                                              │  returns Treehouse worktree, resets ExaminerReceipt)
                                              ▼
                                           COMPLETED
                                              │ (audit living deeds via /edge-drift & prepare-ship)
                                              ▼
                                            IDLE
```

---

## 🌳 Isolated Worktree & Zero-Amnesia Flight Recorder Architecture

### 1. Isolated Worktree Allocation (`treehouse` Primary + Native `git worktree` Fallback)
- Every vertical slice (feature or refactor) runs in a dedicated, isolated git worktree:
  - **Primary (`treehouse`):** Leased via `treehouse get --lease` when installed.
  - **Cross-OS Fallback (Native `git worktree`):** When `treehouse` is absent (Windows/macOS/Linux), `acquire_worktree` automatically falls back to native `git worktree` under `~/.edge/worktrees/<repo>-<hash6>/<sanitized-branch>` outside the repository root.
  - **Antigravity Swarm / Subagent Isolation:** Parallel swarm workers use Antigravity's native `workspace="share"` (or `workspace="branch"`) and land changes before cleanup.
- In feature slices, `brigade start-slice --track feature` leases the worktree upfront, preserving the Zero-Touch Primary Invariant throughout test authoring, surgery, verification, and review.
- The primary checkout stays on `<integration_branch>` (`main` in Pure Core/`typescript`; `development` in `nextjs-drizzle-tailwind`) completely untouched during surgery, verification, and review.
- **Mandatory Cleanup & Zero-Data-Loss Return:**
  - In `guard_staging_to_completed` (`brigade finish-slice`), changes are fast-forward merged (`git merge --ff-only`) into `<integration_branch>`, the worktree is removed and pruned (`git worktree remove` + `prune`), and merged branches are deleted with ancestry-guarded `git branch -d` (unmerged `--pr` branches are preserved).
  - On `brigade abort`, native worktrees with commits ahead of base are never destroyed with `-D`; they are safely renamed to `edge/aborted/<sanitized>-<timestamp>`.
  - Stale or orphaned worktree directories are cleaned via `brigade worktree /path/to/repo --action prune`.

### 2. Living Flight Recorder & Negative Constraints Ledger
- Maintained under `.edge/flight-recorder/<ticket_id>.json` and `<ticket_id>-learnings.md`.
- Tracks every dead end, failed approach, compiler trap, or architectural deadlock.
- Automatically formats and injects a `> [!CAUTION] 🚫 ZERO-AMNESIA FLIGHT RECORDER` alert into station prompts (`brigade ticket --prompt`) so successor agents or retry cycles never repeat proven fatal mistakes.

### 3. Tracker Spec SSOT, Cache & Living Domain Deeds (`edge-drift`)
- **GitHub Issues + Sub-issues SSOT (`tools/tracker/`):** Parent Issues (`spec:draft` -> `spec:approved`) hold specifications and are cached under `.edge/cache/issues/` (never archived). Child sub-issues transition `status:ready` -> `status:in-progress` -> `status:done` on `finish-slice`. Legacy `.edge/specs/`, `tasks-axi`, and `frontier-axi` are soft-deprecated (legacy `.edge/specs/<slice>.md` still archives to `.edge/archive/specs/`).
- **Living Domain Deeds:** Long-lived architectural and domain contracts reside under `docs/domains/<domain>.md` (containing YAML frontmatter with `tracked_paths`).
- **Zero Token Waste Drift Audits:** Running `/edge-drift` (`python3 tools/drift/cli.py check <repo>`) compares git diff against `tracked_paths`. Only domains whose underlying files have changed are audited, resulting in zero token waste for untouched domains.

### 4. Emergency Controls: Escalate & Terminate / Abort
- **`escalate`**: Freezes the FSM safely into `CycleState.PAUSED`, writes an atomic checkpoint, logs the question to the flight recorder, and waits for captain decision.
- **`release`**: Records the captain's binding decision and automatically resumes execution from the exact paused state.
- **`abort`**: Emergency terminate button. Logs the dead-end and optional negative constraint to the flight recorder, terminates worktree processes, calls `treehouse return --force`, and resets the FSM to `IDLE`.

---

## ⚡ CLI Reference & Usage

Run from target repository or plugin directory:

```bash
# 1. Initialize Brigade state in target repository (defaults to active profile integration branch)
brigade init /path/to/repo --base-branch <integration_branch>

# 2. Register persistent station workers (using their conversation_id and optional --model)
brigade register /path/to/repo --role spec_writer --conversation-id <id> --name "Spec Writer" --model flash
brigade register /path/to/repo --role seam_architect --conversation-id <id> --name "Seam Architect" --model flash
brigade register /path/to/repo --role coder --conversation-id <id> --name "Coder" --model flash
brigade register /path/to/repo --role surgeon --conversation-id <id> --name "Refactor Surgeon" --model flash
brigade register /path/to/repo --role examiner --conversation-id <id> --name "Examiner" --model flash
brigade register /path/to/repo --role qa_engineer --conversation-id <id> --name "QA Sommelier" --model flash

# 3. View registered stations
brigade stations /path/to/repo

# 4. Isolated Worktree Yönetimi (Treehouse / Native git worktree Fallback)
brigade worktree /path/to/repo                              # Havuz durumunu göster
brigade worktree /path/to/repo --action lease --branch feat/my-feat  # İzole slot kirala
brigade worktree /path/to/repo --action return --force     # Worktree'yi güvenli iade et
brigade worktree /path/to/repo --action prune              # Yetim worktree dizinlerini temizle

# 5. Şartname Danışman Denetimi (Parent Issue SSOT via tools/tracker)
brigade critique-spec --issue <parent_issue> /path/to/repo

# 6. Dikey Dilim Başlat (Feature: Parent Issue cached to .edge/cache/issues/, Child Issue -> status:in-progress)
brigade start-slice --issue <child_issue> --parent-issue <parent_issue> --name staff-allocation --track feature /path/to/repo
brigade create-refactor-ticket /path/to/repo --slug bookings-leak --track core --rules RULE-ACTION-DB-LEAK --files <source_file> --targets db_leaks=0,max_cc=10 --parent-issue <parent_issue> --hold-captain

# 7. Radar Bilet Triage (Refactor borç defterinden bilet alır ve worktree kiralar)
brigade triage /path/to/repo --track core

# 8. Aktif İstasyon Prompt Payload'unu İncele (Negatif kısıtlar ve worktree yolu içerir)
brigade ticket /path/to/repo --prompt

# 9. Examiner 3-Axis Seal (REVIEW durumunda zorunlu mühür) ve 4-Mühürlü RefactorReceipt
brigade seal-review /path/to/repo --verdict PASS --summary "3-axis & evidence verified" --evidence-reviewed ".edge/qa/proofs/slug.json"
brigade seal-refactor /path/to/repo --slug bookings-leak --base <integration_branch>

# 10. Durum Makinesini İlerlet (Deterministik kapıları çalıştırır; GATE -> REVIEW/QA aşamasında RefactorReceipt sentezler)
brigade advance /path/to/repo

# 11. Dikey Dilimi Tamamla (<integration_branch> Dalına Fast-Forward Merge veya --pr ile AWAITING_MERGE / confirm-merge)
brigade finish-slice /path/to/repo
brigade confirm-merge /path/to/repo

# 12. Specs-to-PR Köprüsü (no-mistakes öncesi PR gövdesi, intent ve One-way/Two-way Door risk analizi)
brigade prepare-ship /path/to/repo --base <staging_or_integration_branch> --format pr

# 11. Yaşayan Alan Senetlerini Denetle (Drift Scanner)
python3 tools/drift/cli.py check /path/to/repo

# 12. Zengin Durum Kartını İncele (Aktif worktree ve eskalasyon durumunu gösterir)
brigade status /path/to/repo

# 13. Acil Durum Butonu: Kaptana Eskalasyon
brigade escalate /path/to/repo --reason "Need schema column clarification"

# 14. Eskalasyonu Kaptan Kararıyla Çöz
brigade release /path/to/repo --decision "Use 'user_display_name' field"

# 15. Acil Durum Butonu: İptal Et, Negatif Kuralı Kaydet ve Worktree'yi Zorla İade Et
brigade abort /path/to/repo --reason "Deadlock under concurrency" --constraint "DO NOT use raw queries without transaction context"
```
