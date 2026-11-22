# Domain: distill

- **Paths:** `tools/distill/**`, `tools/brigade/distill.py`, `skills/edge-distill/**`
- **Owner / DRI:** @edge-distill
- **Concepts:** `watermark-harvest`, `lexical-stack-gate`, `line-budget-ceiling`

## Core Invariants
- **[INV-DISTILL-MODE-ISOLATION]** `PROJECT_MODE` never mutates `edge` plugin rubrics or skills; plugin-level friction routes strictly to `edge_factory_inbox.json`.
  *Enforced by:* `tests/test_distill.py`, `tools/distill/state.py`
- **[INV-DISTILL-LINE-BUDGET]** Distilled rules obey hard physical line caps (`<= 60` lines for `agents/*.md`, `<= 40` lines for `.edge/stations/*.md`, `<= 80` lines for reference rubrics).
  *Enforced by:* `tests/test_distill.py`, `tests/test_distill_skill.py`, `tools/distill/state.py`
- **[INV-DISTILL-ZERO-TOKEN-EXIT]** When `harvest` detects zero unprocessed sessions and zero pending candidates, distillation exits immediately with 0 LLM tokens spent.
  *Enforced by:* `tests/test_distill.py`, `tests/test_distill_skill.py`, `tools/distill/cli.py`

## Adopted Patterns
- **[PAT-DISTILL-WATERMARK-HARVEST]** `TranscriptGraphHarvester` scans transcripts deterministically using watermark state and wraps digests in `<untrusted_telemetry_digest>`.
  *Enforced by:* `tests/test_distill.py`, `tools/distill/harvester.py`
- **[PAT-DISTILL-STACK-GATE]** `LexicalStackGate` separates `REPO_LOCAL` overlays from cross-project `PLUGIN_CANDIDATE` rules before Captain approval via the 4-Line Commander Decision Card.
  *Enforced by:* `tests/test_distill.py`, `tools/distill/state.py`, `skills/edge-distill/SKILL.md`
