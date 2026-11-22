# Domain: brigade

- **Paths:** `tools/brigade/cli.py`, `tools/brigade/fsm.py`, `tools/brigade/models.py`, `tools/brigade/worktree.py`, `tools/brigade/flight_recorder.py`, `tools/brigade/navigation.py`, `tools/brigade/tasks_bridge.py`, `tools/brigade/refactor_receipt.py`, `tools/common/**`, `skills/edge-brigade/**`, `skills/edge-core-refactor/**`, `skills/edge-ui-refactor/**`, `agents/seam-architect.md`, `agents/coder.md`, `agents/surgeon.md`
- **Owner / DRI:** @edge-brigade
- **Concepts:** `zero-touch-worktree`, `exit-code-fsm`, `atomic-state-store`, `bounded-navigation`

## Core Invariants
- **[INV-BRIGADE-ZERO-TOUCH-TREE]** Production code and test edits execute exclusively inside a leased Treehouse worktree, never in the primary working tree.
  *Enforced by:* `tests/test_worktree_and_flight_recorder.py`, `tools/brigade/worktree.py`
- **[INV-BRIGADE-TEST-IMMUTABLE]** `CODER` and `SURGEON` never modify, delete, or weaken tests authored by `SEAM_ARCHITECT` to force green runs.
  *Enforced by:* `tests/test_brigade.py`, `agents/coder.md`, `agents/surgeon.md`
- **[INV-BRIGADE-ATOMIC-STATE]** All `.edge/brigade.json` and FlightRecorder mutations write atomically via temp file + `os.replace`.
  *Enforced by:* `tests/test_worktree_and_flight_recorder.py`, `tools/brigade/flight_recorder.py`

## Adopted Patterns
- **[PAT-BRIGADE-EXITCODE-FSM]** Every `BrigadeFSM` phase transition is gated by deterministic subprocess exit codes (`RED_TEST` -> `SURGERY` -> `VERIFY` -> `GATE` -> `REVIEW` -> `STAGING`).
  *Enforced by:* `tests/test_brigade.py`, `tools/brigade/fsm.py`, `tools/brigade/cli.py`
- **[PAT-BRIGADE-BOUNDED-NAV]** `build_navigation_context` slices `specs/INDEX.md`, scoped `CONTEXT.md`, domain deeds, and git co-changes into <=15 lines with `[STALE]` link annotation.
  *Enforced by:* `tests/test_navigation.py`, `tests/test_common.py`, `tests/test_toon.py`, `tools/brigade/navigation.py`
