# Domain: distill

- **Owner / DRI:** @edge-distill
- **Concepts:** `watermark-harvest`, `lexical-stack-gate`, `line-budget-ceiling`

## Living Invariants
- **[INV-DISTILL-MODE-ISOLATION]** `PROJECT_MODE` never mutates plugin rubrics or skills; plugin-level friction is queued separately for factory review.
- **[INV-DISTILL-LINE-BUDGET]** Distilled rules obey strict physical line caps (`<= 60` lines for agent rubrics, `<= 40` lines for station overlays, `<= 80` lines for reference lenses).
- **[INV-DISTILL-ZERO-TOKEN-EXIT]** When harvesting finds zero unprocessed sessions and zero pending candidates, distillation exits immediately with zero model tokens spent.

## Adopted Patterns
- **[PAT-DISTILL-WATERMARK-HARVEST]** Incremental session harvesting tracks processed watermarks and wraps extracted telemetry as untrusted observational data.
- **[PAT-DISTILL-STACK-GATE]** Stack gating routes `REPO_LOCAL` findings to project overlays and `PLUGIN_CANDIDATE` rules through multi-project validation and the 4-Line Commander Decision Card.
