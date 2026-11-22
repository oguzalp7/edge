# Domain: orchestration

- **Paths:** `skills/edge-orchestrator/**`, `skills/edge-pro/**`, `skills/edge-ultra/**`, `skills/edge-antigraveyard/**`, `skills/edge-agentecho/**`, `skills/edge-technical-writing/**`, `skills/edge-gnhf/**`, `rules/**`, `agents/orchestrator.md`, `agents/spec-writer.md`, `agents/spec-critic.md`, `agents/researcher.md`, `tools/brigade/orchestrator_guard.py`, `tools/brigade/stations.py`, `tools/brigade/spec_critic.py`, `tools/brigade/tier.py`, `tools/gnhf/**`, `hooks.json`
- **Owner / DRI:** @edge-orchestration
- **Concepts:** `zero-handoff-guard`, `elephant-station-reuse`, `goldfish-ephemeral-review`, `strategic-context-fork`

## Core Invariants
- **[INV-ORCH-HOOK-LATENCY]** Orchestrator hook guards run deterministically in-process without LLM calls and block direct orchestrator source/test edits.
  *Enforced by:* `tests/test_brigade_guard.py`, `tests/test_hook_logic.py`, `tools/brigade/orchestrator_guard.py`, `hooks.json`
- **[INV-ORCH-ELEPHANT-REUSE]** Persistent elephant stations (`SPEC_WRITER`, `RESEARCHER`, `SEAM_ARCHITECT`, `CODER`, `SURGEON`, `QA_ENGINEER`) reuse active conversation IDs in the green zone instead of spawning duplicates.
  *Enforced by:* `tests/test_brigade_guard.py`, `tools/brigade/orchestrator_guard.py`
- **[INV-ORCH-GOLDFISH-FRESH]** Ephemeral goldfish stations (`SPEC_CRITIC`, `EXAMINER`) always spawn with zero prior coder/surgeon baggage to eliminate confirmation bias.
  *Enforced by:* `tests/test_spec_critic.py`, `tools/brigade/spec_critic.py`, `tools/brigade/stations.py`

## Adopted Patterns
- **[PAT-ORCH-ZERO-HANDOFF]** Orchestrator delegates all code reading and editing to canonical stations while keeping intake and `grill-with-docs` glossary alignment in the green zone.
  *Enforced by:* `tests/test_tier_switch.py`, `tests/test_gnhf.py`, `tools/brigade/tier.py`
- **[PAT-ORCH-STRATEGIC-FORK]** Reviewers (`EXAMINER`) fork domain vocabulary from `spec_writer` or `researcher`, never from `coder` or `surgeon`.
  *Enforced by:* `tools/brigade/stations.py`, `skills/edge-orchestrator/SKILL.md`
