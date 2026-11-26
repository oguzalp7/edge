# 🐝 Swarm vs. Brigade Playbook: Topology, Guardrails & Decision Rules

> **Authoritative Playbook**  
> **Status:** ACTIVE  
> **Scope:** High-level engineering coordination across Edge Brigade deterministic pipelines and native Antigravity horizontal swarms.

---

## 🎯 1. Overview & Core Philosophy

The Edge engineering engine supports two distinct multi-agent paradigms:

1. **Deterministic Brigade Pipeline (`edge-brigade`):**  
   A hardcoded Finite State Machine (FSM) where state transitions (`RED_TEST` $\rightarrow$ `SURGERY` $\rightarrow$ `VERIFY` $\rightarrow$ `REVIEW` $\rightarrow$ `GATE` $\rightarrow$ `STAGING`) are governed 100% by OS process exit codes and strict data invariants. Designed for sequential vertical slice feature delivery, TDD anchors, and architectural refactoring surgeries.

2. **Native Horizontal Swarm (`native_swarm` / `/swarm`):**  
   A multi-agent parallel execution pattern communicating through a shared message board. Designed for behavior-preserving horizontal/sharded refactoring across independent files, A/B architectural spikes with `workspace:"share"`, and multi-angle Root Cause Analysis (RCA).

---

## 🧭 2. Topology & Decision Matrix

```
                              ENGINEERING TASK INTAKE
                                         │
                   Is the task a vertical slice feature,
                   schema change, or contract mutation?
                               /                   \
                             YES                    NO
                             /                        \
              ┌────────────────────────┐    Is it wide, independent sharding
              │   EDGE BRIGADE FSM     │    or multi-angle experimentation?
              │ (Deterministic TDD,    │               /             \
              │  Seams, Strict Gates,  │             YES              NO
              │  Worktree Pool Slot)   │             /                  \
              └────────────────────────┘   ┌────────────────────┐   ┌───────────────────┐
                                           │   NATIVE SWARM     │   │ SINGLE SUBAGENT   │
                                           │ (Sharded Refactor, │   │ (Read-Only Search,│
                                           │  A/B Spikes, RCA)  │   │  Simple Mutation) │
                                           └────────────────────┘   └───────────────────┘
```

| Dimension | Edge Brigade (`edge-brigade`) | Native Swarm (`/swarm`) |
| :--- | :--- | :--- |
| **Topology** | Deep, vertical, sequential dependencies (DB $\rightarrow$ Core $\rightarrow$ API $\rightarrow$ UI). | Wide, horizontal, independent files or parallel explorations. |
| **Contract Stability** | Mutating contracts, new schemas, new API surfaces. | Fixed, behavior-preserving transformations across N files. |
| **Quality Control** | Strict FSM state transitions (`RED_TEST` $\rightarrow$ `SURGERY` $\rightarrow$ `VERIFY` $\rightarrow$ `REVIEW` $\rightarrow$ `GATE`). | Parallel workers reporting to shared board; terminal gate verification on merge. |
| **Workspace Mode** | Dedicated isolated worktree (`treehouse` pool slot or native `~/.edge/worktrees/<repo>-<hash6>/<branch>`). | `workspace:"share"` for parallel branches or `workspace:"inherit"` for read-only workers. |
| **Primary Use Cases** | Vertical Slice features, core architectural refactors, database schema expansions. | Sharded mass refactors (AST/regex updates across N files), competing A/B architectural spikes, multi-angle RCA. |

---

## 🛡️ 3. Lightweight Swarm Guardrails

When native `/swarm` is chosen for horizontal tasks, the following three rules are strictly enforced:

1. **Daemon Ban (No `narrator`, No `monitor`):**  
   Autonomous swarms MUST NOT spawn standing daemons (`narrator` or `swarm_monitor`). Daemons continuously consume LLM tokens and quota without contributing to code artifacts. The coordinator inspects status via `swarm(action:"status")` on demand.
2. **Quota Conservation Default (`model: "flash"`):**  
   Every spawned worker must be explicitly pinned to `model: "flash"` in the `swarm add` directive unless the human captain explicitly mandates a higher tier (e.g. `claude-opus-5-5-high`).
3. **Deterministic Gate on Landing:**  
   Before any shared worktree or worker branch is merged into the base branch, `python3 tools/gate.py` must execute with exit code 0.

---

## 🧬 4. Strategic Domain Context Forking Architecture

In Antigravity, subagents and swarm workers support context branching via `fork:"<member>"` or `fork_from` parameters. To balance rich domain vocabulary against confirmation bias, Edge enforces Strategic Domain Context Forking:

```
  ORCHESTRATOR (Intake & High-Level Directives)
       │
       ▼
  SPEC_WRITER (Deep Domain Vocabulary, User Requirements, Boundaries)
       │
       ├────────────────────────────────────────┐
       │                                        │  [Domain Lexicon & Spec Clone]
       ▼                                        ▼  (fork: "spec_writer")
  SEAM_ARCHITECT (Contracts & Red Tests)    EXAMINER (Dual-Axis Review)
       │                                    - Axis 1: Standards & Fowler Smells
       ▼                                    - Axis 2: Architectural & Spec Boundaries
  CODER / SURGEON (Implementation Diff)     - ZERO Implementation Memory / Bias!
       │                                        ▲
       └────────────────────────────────────────┘
                    [Inspects Git Diff Only]
```

### The Examiner Bias Neutrality Invariant
- **Forking Rule:** `EXAMINER` MUST `fork` from `spec_writer` or `researcher`.
- **Negative Invariant:** `EXAMINER` must NEVER inherit conversational history or `fork` from `coder` or `surgeon`.
- **Reason:** Forking from implementation workers introduces confirmation bias—the examiner absorbs the coder's defensive reasoning, implementation compromises, and blind spots. Forking from `spec_writer` or `researcher` transfers clean domain vocabulary, specifications, and boundary contracts while keeping the reviewer 100% neutral toward the actual git diff.

---

## 🗂️ 5. Shared Workspace Guidance

When spawning swarm workers with `swarm(action: "add")`:
- **`workspace: "share"`:** Use when authoring or refactoring parallel slices where workers edit or build simultaneously.
- **`workspace: "branch"`:** Use for speculative A/B spikes where complete isolation is required.
- **`workspace: "inherit"`:** Use for read-only workers (e.g. multi-angle researchers).
- **Merge Protocol:** Land work with fast-forward merge after running `python3 tools/gate.py`.
