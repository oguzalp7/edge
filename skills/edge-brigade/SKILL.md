---
name: edge-brigade
description: Michelin Station (Brigade de Cuisine) deterministic State Machine Engine. Orchestrates persistent station workers (Surgeon, Standards Examiner, Spec Examiner, Expediter) with hardcoded state transitions governed by OS exit codes and data invariants rather than LLM self-assessment.
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
  |                           EXPEDITER (Aboyeur)                          |
  |        Triage Tickets --> Dispatch Stations --> Squash Merge --> PR    |
  +-------------------+--------------------------------+-------------------+
                      |                                |
       [TRACK: FEATURE]                                [TRACK: REFACTOR]
       +--------------+---------------+ +--------------+---------------+
       | SPEC WRITER (lavish-axi Gate)| |   SURGEON (Chef de Partie)    |
       | RESEARCHER (Root Cause / RCA)| |   Architecture & Decoupling   |
       | SEAM ARCHITECT (Red Tests)   | |   (Contraction Decoupled)     |
       | CODER (Turns Red to Green)   | |                               |
       +--------------+---------------+ +--------------+---------------+
                      |                                |
                      +----------------+---------------+
                                       |
                                       v
       +------------------------------+ +------------------------------+
       |  STANDARDS EXAMINER (Sous)   | |    SPEC EXAMINER (Maitre d') |
       |  Fowler Smells & Standards   | |    3-Tier Decoupling & Invar |
       +------------------------------+ +------------------------------+
                                       |
                                       v
       +---------------------------------------------------------------+
       |                 QA_ENGINEER (Sommelier)                       |
       |     E2E Browser QA (chrome-devtools-axi) & frontier-axi       |
       +---------------------------------------------------------------+
```

### The 9 Brigade Stations (Kadro Yapılanması):
1. **EXPEDITER (`expediter` / Aboyeur)**:
   - **Role:** Kitchen coordinator and dispatcher.
   - **Constraint:** Squash-merges verified branches, refreshes debt ledgers, and triggers PR creation via `no-mistakes`.
2. **SPEC_WRITER (`spec_writer`)**:
   - **Role:** Ubiquitous language translator & N-Spec slicer.
   - **Constraint:** Condenses user story into 3-4 plain English sentences. Enforces Pocock/Dexter Horthy vertical slice completeness (DB -> Core -> API -> UI). **Visual Approval Gate (`lavish-axi`):** If UI is touched, MUST author interactive HTML in `.lavish/<feature>.html` and obtain user approval before coding.
3. **RESEARCHER (`researcher`)**:
   - **Role:** Deep codebase exploration, AST tracing, external documentation verification, and root cause analysis.
   - **Constraint:** Zero production code mutation; delivers evidence-backed seam recommendations.
4. **SEAM_ARCHITECT (`seam_architect`)**:
   - **Role:** Michael Feathers seam architect & contract author.
   - **Constraint:** Declares TypeScript interfaces and writes **RED Unit/Contract Tests** that initially fail (TDD anchor).
5. **CODER (`coder`)**:
   - **Role:** Production code worker.
   - **Constraint:** Turns red tests GREEN with minimal, clean code. **Test Immutability:** Cannot modify or loosen test assertions.
6. **SURGEON (`surgeon` / Chef de Partie)**:
   - **Role:** Refactor & structural cleanup specialist.
   - **Constraint:** Decouples bloated controllers and extracts domain repositories. (Target contraction $\Delta	ext{SLOC} < 0$ is decoupled; structural cleanliness and test greenness govern quality).
7. **STANDARDS_EXAMINER (`standards_examiner` / Sous Chef)**:
   - **Role:** Dual-axis review against `coding_standards.md` and Fowler code smells.
   - **Constraint:** Differentiates hard standard breaches (index signature tampering, missing transactions) from baseline smells.
8. **SPEC_EXAMINER (`spec_examiner` / Maitre d')**:
   - **Role:** Architectural invariants audit and scope creep detection.
   - **Constraint:** Verifies 3-tier decoupling and ensures implementation does not exceed spec boundaries.
9. **QA_ENGINEER (`qa_engineer` / Sommelier)**:
   - **Role:** End-to-end browser verification, visual quality assurance, and user journey testing.
   - **Protocol:** Receives translated user scenarios mapped to project ubiquitous domain vocabulary by the Orchestrator. Drives live browser interactions via `chrome-devtools-axi` (primary) or `chrome-devtools-mcp` (fallback).
   - **Constraint:** Strictly zero production code mutation (`src/**`, `app/**`, `lib/**`, `db/**`). Documents defects with reproduction steps, network payloads, console errors, and screenshots. Parks non-blocking UX issues to `frontier-axi`.

---

## 🔄 State Machine Lifecycle & Deterministic Guards

Transitions are **stateless reducers** governed purely by process exit codes and hard data assertions:

```
   IDLE
     |  (triage from .edge/ledger/core.json)
     v
   TRIAGE
     |  (validate target file & branch)
     v
   SURGERY
     |  (guard_surgery: git diff schema==0, target_contraction<0, net_sloc<=budget)
     v
   VERIFY
     |  (guard_verify: vitest exit code==0, tsc --noEmit exit code==0)
     v
   REVIEW ----[CRITICAL findings]----> POLISH
     |                                    |
     | [0 critical findings]              | (guard_polish: tsc exit==0, tests pass)
     v                                    v
   GATE <---------------------------------+
     |  (guard_gate: python tools/gate.py exit code==0)
     v
   STAGING
     |  (guard_staging: git merge --ff-only into development, returns Treehouse worktree, resolves flight recorder)
     v
   COMPLETED
     |  (reset to IDLE for next ticket)
     v
   IDLE
```

---

## 🌳 Isolated Worktree & Zero-Amnesia Flight Recorder Architecture

### 1. Treehouse Worktree Pool Allocation (`treehouse get --lease`)
- Every vertical slice (feature or refactor) runs in a dedicated, isolated git worktree leased from the Treehouse pool (`/home/oguz/.treehouse/pool/slot-N`).
- The primary checkout stays on `development` completely untouched during surgery, verification, and review.
- In `guard_staging_to_completed`, changes are fast-forward merged (`git merge --ff-only`) into `development`, and the worktree slot is returned cleanly to the pool.

### 2. Living Flight Recorder & Negative Constraints Ledger
- Maintained under `.edge/flight-recorder/<ticket_id>.json` and `<ticket_id>-learnings.md`.
- Tracks every dead end, failed approach, compiler trap, or architectural deadlock.
- Automatically formats and injects a `> [!CAUTION] 🚫 ZERO-AMNESIA FLIGHT RECORDER` alert into station prompts (`brigade ticket --prompt`) so successor agents or retry cycles never repeat proven fatal mistakes.

### 3. Emergency Controls: Escalate & Terminate / Abort
- **`escalate`**: Freezes the FSM safely into `CycleState.PAUSED`, writes an atomic checkpoint, logs the question to the flight recorder, and waits for captain decision.
- **`release`**: Records the captain's binding decision and automatically resumes execution from the exact paused state.
- **`abort`**: Emergency terminate button. Logs the dead-end and optional negative constraint to the flight recorder, terminates worktree processes, calls `treehouse return --force`, and resets the FSM to `IDLE`.

---

## ⚡ CLI Reference & Usage

Run from target repository or plugin directory:

```bash
# 1. Initialize Brigade state in target repository (Default base branch: development)
python3 tools/brigade/cli.py init /path/to/repo --base-branch development

# 2. Register persistent station workers (using their conversation_id)
python3 tools/brigade/cli.py register /path/to/repo --role surgeon --conversation-id <id> --name "Refactor Surgeon"
python3 tools/brigade/cli.py register /path/to/repo --role standards_examiner --conversation-id <id> --name "Standards Examiner"
python3 tools/brigade/cli.py register /path/to/repo --role spec_examiner --conversation-id <id> --name "Spec Examiner"
python3 tools/brigade/cli.py register /path/to/repo --role qa_engineer --conversation-id <id> --name "QA Sommelier"

# 3. View registered stations
python3 tools/brigade/cli.py stations /path/to/repo

# 4. Treehouse Worktree Yönetimi
python3 tools/brigade/cli.py worktree /path/to/repo                              # Havuz durumunu göster
python3 tools/brigade/cli.py worktree /path/to/repo --action lease --branch feat/my-feat  # İzole slot kirala
python3 tools/brigade/cli.py worktree /path/to/repo --action return --force     # Worktree'yi havuza iade et

# 5. Dikey Dilim Başlat (Feature / Refactor için otomatik Treehouse Worktree kiralar)
python3 tools/brigade/cli.py start-slice /path/to/repo --name staff-allocation --track feature

# 6. Radar Bilet Triage (Mevcut borç defterinden bilet alır ve worktree kiralar)
python3 tools/brigade/cli.py triage /path/to/repo --track core

# 7. Aktif İstasyon Prompt Payload'unu İncele (Negatif kısıtlar ve worktree yolu içerir)
python3 tools/brigade/cli.py ticket /path/to/repo --prompt

# 8. Durum Makinesini İlerlet (Deterministik kapıları çalıştırır)
python3 tools/brigade/cli.py advance /path/to/repo

# 9. Dikey Dilimi Tamamla (development Dalına Fast-Forward Merge & Worktree İadesi)
python3 tools/brigade/cli.py finish-slice /path/to/repo

# 10. Zengin Durum Kartını İncele (Aktif worktree ve eskalasyon durumunu gösterir)
python3 tools/brigade/cli.py status /path/to/repo

# 11. Acil Durum Butonu: Kaptana Eskalasyon
python3 tools/brigade/cli.py escalate /path/to/repo --reason "Need schema column clarification"

# 12. Eskalasyonu Kaptan Kararıyla Çöz
python3 tools/brigade/cli.py release /path/to/repo --decision "Use 'user_display_name' field"

# 13. Acil Durum Butonu: İptal Et, Negatif Kuralı Kaydet ve Worktree'yi Zorla İade Et
python3 tools/brigade/cli.py abort /path/to/repo --reason "Deadlock under concurrency" --constraint "DO NOT use raw queries without transaction context"
```
