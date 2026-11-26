# Edge Plugin Context

Authoritative self-ontology for the `edge` plugin repository.

## Domain Map

| Domain | Paths | Owner |
| :--- | :--- | :--- |
| `orchestration` | `skills/edge-orchestrator/**`, `skills/edge-pro/**`, `skills/edge-ultra/**`, `skills/edge-antigraveyard/**`, `skills/edge-agentecho/**`, `skills/edge-technical-writing/**`, `skills/edge-gnhf/**`, `rules/**`, `agents/orchestrator.md`, `agents/spec-writer.md`, `agents/spec-critic.md`, `agents/researcher.md`, `tools/brigade/orchestrator_guard.py`, `tools/brigade/stations.py`, `tools/brigade/spec_critic.py`, `tools/brigade/tier.py`, `tools/gnhf/**`, `hooks.json` | @edge-orchestration |
| `brigade` | `tools/brigade/cli.py`, `tools/brigade/fsm.py`, `tools/brigade/models.py`, `tools/brigade/worktree.py`, `tools/brigade/flight_recorder.py`, `tools/brigade/navigation.py`, `tools/brigade/tasks_bridge.py`, `tools/brigade/tracker_hooks.py`, `tools/brigade/refactor_receipt.py`, `tools/tracker/**`, `tools/common/**`, `skills/edge-brigade/**`, `skills/edge-core-refactor/**`, `skills/edge-ui-refactor/**`, `agents/seam-architect.md`, `agents/coder.md`, `agents/surgeon.md` | @edge-brigade |
| `distill` | `tools/distill/**`, `tools/brigade/distill.py`, `skills/edge-distill/**` | @edge-distill |
| `drift` | `tools/drift/**`, `skills/edge-drift/**` | @edge-drift |
| `quality-gates` | `tools/gate.py`, `tools/rules.py`, `tools/audit/**`, `tools/ui_audit/**`, `tools/test_audit/**`, `tools/radar/**`, `tools/mutator/**`, `tools/brigade/qa_fiber.py`, `tools/brigade/security_audit.py`, `tools/brigade/smoke_routes.py`, `skills/edge-audit/**`, `skills/edge-ui-audit/**`, `skills/edge-tests-audit-typescript/**`, `skills/edge-radar/**`, `skills/edge-mutator/**`, `skills/edge-security-audit/**`, `agents/examiner.md`, `agents/qa-engineer.md` | @edge-quality |
| `delivery` | `tools/brigade/ship_prep.py`, `tools/brigade/ship_tracker.py`, `skills/edge-ship/**`, `skills/edge-no-mistakes/**` | @edge-delivery |

## Closed Concept Glossary

| Concept | Code Symbol / File | Meaning |
| :--- | :--- | :--- |
| `zero-handoff-guard` | `handle_pre_tool`, `handle_pre_invocation` (`tools/brigade/orchestrator_guard.py`) | Hard hook gate blocking orchestrator source/test mutations and unsealed transitions |
| `elephant-station-reuse` | `StationStore`, `find_active_station` (`tools/brigade/orchestrator_guard.py`) | Persistent role reuse via `send_message` in the green token zone |
| `goldfish-ephemeral-review` | `run_spec_critique`, `StationRegistry` (`tools/brigade/spec_critic.py`, `tools/brigade/stations.py`) | Fresh zero-history spawn for `SPEC_CRITIC` and `EXAMINER` to prevent bias |
| `strategic-context-fork` | `build_swarm_dispatch_directive` (`tools/brigade/stations.py`) | Forking reviewer context from `spec_writer` or `researcher`, never `coder`/`surgeon` |
| `zero-touch-worktree` | `acquire_worktree`, `return_worktree` (`tools/brigade/worktree.py`) | Mandatory Treehouse worktree isolation before code or test edits |
| `exit-code-fsm` | `BrigadeFSM`, `ProofVerifier` (`tools/brigade/fsm.py`) | Deterministic phase transition state machine driven by CLI exit codes |
| `atomic-state-store` | `DriftStateStore.save`, `FlightRecorder` (`tools/drift/models.py`, `tools/brigade/flight_recorder.py`) | Crash-safe temp-write and `os.replace` persistence for `.edge/` state |
| `bounded-navigation` | `build_navigation_context` (`tools/brigade/navigation.py`) | Bounded <=15-line domain/index/glossary context slice with `[STALE]` checking |
| `github-issues-ssot` | `resolve_backend`, `GhAxiBackend`, `LocalTrackerBackend` (`tools/tracker/backends.py`, `tools/tracker/gh_axi_backend.py`, `tools/tracker/local_backend.py`) | GitHub Issues and native sub-issues SSOT (`gh-axi -> gh -> local`) with offline/no-remote fallback |
| `fail-fast-tracker-auth` | `TrackerAuthError`, `preflight_ticket_tracker` (`tools/tracker/models.py`, `tools/brigade/tracker_hooks.py`) | Fail-fast exit code 2 preflight on missing binary or auth/network failure before git mutations |
| `ephemeral-spec-cache` | `cache_issue_spec`, `resolve_slice_issue_spec` (`tools/tracker/cache.py`, `tools/brigade/tracker_hooks.py`) | Non-archived primary-root local cache of tracker issue specifications |
| `watermark-harvest` | `TranscriptGraphHarvester`, `DistillWatermarkState` (`tools/distill/harvester.py`, `tools/distill/models.py`) | Incremental zero-token session harvesting keyed by conversation watermark |
| `lexical-stack-gate` | `LexicalStackGate`, `CandidatePool` (`tools/distill/state.py`) | Deterministic classification between `REPO_LOCAL` overlays and `PLUGIN_CANDIDATE` rules |
| `line-budget-ceiling` | `check_line_budget`, `collect_budget_targets` (`tools/distill/state.py`) | Hard physical line caps on agent rubrics (`<=60`L) and station overlays (`<=40`L) |
| `zero-token-drift-gate` | `check_drift`, `validate_ontology` (`tools/drift/scanner.py`) | SHA and `tracked_paths` diff gate plus deterministic ontology validator |
| `domain-deed` | `CanonicalDomainDoc`, `parse_canonical_domain_doc` (`tools/drift/models.py`) | Authoritative in-place `docs/<domain>/DOMAIN.md` contract ("Tapu") |
| `deterministic-quality-gate` | `EdgeVerificationGate`, `check_differential_mutation_gate` (`tools/gate.py`) | Pre-LLM static gate enforcing migration lock, layer purity, and differential checks |
| `complexity-ceiling` | `analyze_file_crap`, `compute_crap` (`tools/audit/crapper.py`) | Cyclomatic complexity non-regression and `CC <= 10` ceiling on clean/new files |
| `two-tier-delivery` | `prepare_ship_payload`, `validate_branch_topology` (`tools/brigade/ship_prep.py`) | Enforced `worktree -> development -> staging` split-PR and release-PR chain |
| `refactor-receipt-binding` | `RefactorReceipt`, `RefactorReceiptVerifier` (`tools/brigade/refactor_receipt.py`) | Commit-SHA and file-hash bound receipt sealing zero-behavior-change refactors |
| `one-way-door-brake` | `classify_merge_danger` (`tools/brigade/ship_prep.py`) | Automatic merge brake for public API breaks, auth paths, or oversized diffs |
