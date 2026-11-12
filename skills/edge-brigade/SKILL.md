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
       |                   EXAMINER (Sous / Maitre d')                 |
       |       Unified Dual-Axis Standards & Architectural Invariants  |
       +-------------------------------+-------------------------------+
                                       |
                                       v
       +---------------------------------------------------------------+
       |                 QA_ENGINEER (Sommelier)                       |
       |  E2E Multi-Agent Browser Delegation & Behavioral Proof Gate   |
       +-------------------------------+-------------------------------+
                                       |
                                       v
       +---------------------------------------------------------------+
       |             Deterministic Merge (brigade finish-slice)        |
       |             Spec Archival & /edge-drift Contract Audit        |
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
   - **Role:** Unified dual-axis review: `coding_standards.md`/Fowler code smells and architectural invariants/scope creep in a single concise pass (< 350 words).
   - **Constraint:** Strictly read-only. Distinguishes hard violations from judgement calls; skips deterministic checks enforced by `gate.py`.
8. **QA_ENGINEER (`qa_engineer` / Sommelier)**:
   - **Role:** End-to-end browser verification, visual quality assurance, and user journey testing.
   - **Protocol:** Receives translated user scenarios mapped to project ubiquitous domain vocabulary by the Orchestrator. Acts as the QA architect and delegates physical browser interactions to the built-in `browser` subagent (`TypeName: "browser"`, `Model: "flash"`). Stages Lavish references to `<Artifact Directory>/browser_sandbox/references/`. Enforces state persistence via DOM reload and backend DB/state cross-checks (`run_command`). Synthesizes physical Behavioral Proof Receipt (`.edge/qa/proofs/<slug>.json`) to unlock advancement to STAGING.
   - **Constraint:** Strictly zero production code mutation (`src/**`, `app/**`, `lib/**`, `db/**`). Documents defects with reproduction steps, network payloads, console errors, and screenshots. Parks non-blocking UX issues to `frontier-axi`.

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
                                              │ (guard_verify: vitest exit==0, tsc --noEmit exit==0)
                                              ▼
                                           REVIEW ----[CRITICAL findings]----> POLISH
                                              │                                    │
                                              │ [0 critical findings]              │ (guard_polish: tsc exit==0, tests pass)
                                              ▼                                    ▼
                                            GATE <─────────────────────────────────+
                                              │ (guard_gate: python tools/gate.py exit code==0)
                                              ▼
                                           STAGING
                                              │ (guard_staging: git merge --ff-only into development,
                                              │  archives .edge/specs/<slice>.md to .edge/archive/specs/,
                                              │  returns Treehouse worktree, resolves flight recorder)
                                              ▼
                                           COMPLETED
                                              │ (audit living deeds via /edge-drift)
                                              ▼
                                            IDLE
```

---

## 🌳 Isolated Worktree & Zero-Amnesia Flight Recorder Architecture

### 1. Treehouse Worktree Pool Allocation (`treehouse get --lease`)
- Every vertical slice (feature or refactor) runs in a dedicated, isolated git worktree leased from the Treehouse pool (`/home/oguz/.treehouse/pool/slot-N`).
- In feature slices, `brigade start-slice --track feature` leases the worktree upfront, preserving the Zero-Touch Primary Invariant throughout test authoring, surgery, verification, and review.
- The primary checkout stays on `development` completely untouched during surgery, verification, and review.
- In `guard_staging_to_completed`, changes are fast-forward merged (`git merge --ff-only`) into `development`, and the worktree slot is returned cleanly to the pool.

### 2. Living Flight Recorder & Negative Constraints Ledger
- Maintained under `.edge/flight-recorder/<ticket_id>.json` and `<ticket_id>-learnings.md`.
- Tracks every dead end, failed approach, compiler trap, or architectural deadlock.
- Automatically formats and injects a `> [!CAUTION] 🚫 ZERO-AMNESIA FLIGHT RECORDER` alert into station prompts (`brigade ticket --prompt`) so successor agents or retry cycles never repeat proven fatal mistakes.

### 3. Ephemeral Spec Archival & Living Domain Deeds (`edge-drift`)
- **Scaffolding Spec Archival:** Once a slice successfully merges in `finish-slice`, its ephemeral specification (`.edge/specs/<slice>.md`) is automatically moved to `.edge/archive/specs/`.
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
# 1. Initialize Brigade state in target repository (Default base branch: development)
brigade init /path/to/repo --base-branch development

# 2. Register persistent station workers (using their conversation_id and optional --model)
brigade register /path/to/repo --role spec_writer --conversation-id <id> --name "Spec Writer" --model flash
brigade register /path/to/repo --role seam_architect --conversation-id <id> --name "Seam Architect" --model flash
brigade register /path/to/repo --role coder --conversation-id <id> --name "Coder" --model flash
brigade register /path/to/repo --role surgeon --conversation-id <id> --name "Refactor Surgeon" --model flash
brigade register /path/to/repo --role examiner --conversation-id <id> --name "Examiner" --model flash
brigade register /path/to/repo --role qa_engineer --conversation-id <id> --name "QA Sommelier" --model flash

# 3. View registered stations
brigade stations /path/to/repo

# 4. Treehouse Worktree Yönetimi
brigade worktree /path/to/repo                              # Havuz durumunu göster
brigade worktree /path/to/repo --action lease --branch feat/my-feat  # İzole slot kirala
brigade worktree /path/to/repo --action return --force     # Worktree'yi havuza iade et

# 5. Şartname Danışman Denetimi (Cross-Provider Spec Critic)
brigade critique-spec /path/to/repo --spec .edge/specs/<slice-adi>.md

# 6. Dikey Dilim Başlat (Feature için worktree peşin kiralanır ve RED_TEST durumunda başlar)
brigade start-slice /path/to/repo --name staff-allocation --track feature

# 7. Radar Bilet Triage (Refactor borç defterinden bilet alır ve worktree kiralar)
brigade triage /path/to/repo --track core

# 8. Aktif İstasyon Prompt Payload'unu İncele (Negatif kısıtlar ve worktree yolu içerir)
brigade ticket /path/to/repo --prompt

# 9. Durum Makinesini İlerlet (Deterministik kapıları çalıştırır)
brigade advance /path/to/repo

# 10. Dikey Dilimi Tamamla (development Dalına Fast-Forward Merge, Şartname Arşivleme & Worktree İadesi)
brigade finish-slice /path/to/repo

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
