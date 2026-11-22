# Domain: delivery

- **Paths:** `tools/brigade/ship_prep.py`, `skills/edge-ship/**`, `skills/edge-no-mistakes/**`
- **Owner / DRI:** @edge-delivery
- **Concepts:** `two-tier-delivery`, `refactor-receipt-binding`, `one-way-door-brake`

## Core Invariants
- **[INV-DELIVERY-DEV-FIRST]** Slice shipping defaults to `development` (`Tier 1: 1 Spec = 1 PR -> development`) and blocks direct slice-to-staging promotion without `--allow-topology-override`.
  *Enforced by:* `tests/test_refactor_receipt_and_ship.py`, `tests/test_brigade.py`, `tools/brigade/ship_prep.py`
- **[INV-DELIVERY-RECEIPT-BINDING]** Refactor PRs require a non-stale `.edge/receipts/refactor/<slug>.json` receipt bound to `(commit_sha, changed_files_hash)`.
  *Enforced by:* `tests/test_refactor_receipt_and_ship.py`, `tools/brigade/refactor_receipt.py`, `tools/brigade/ship_prep.py`
- **[INV-DELIVERY-LEAN-PR]** Shipped PR bodies remain bounded to `## Summary` (with 1-Minute Briefing) and `## Evidence` (`Spec Expectations vs. Realization` + `Examiner 3-Axis Seal`).
  *Enforced by:* `tests/test_brigade.py`, `skills/edge-ship/SKILL.md`, `tools/brigade/ship_prep.py`

## Adopted Patterns
- **[PAT-DELIVERY-TWO-TIER]** Per-spec `ship/<slug>` branches merge to `development` before consolidated `development -> staging` release PRs with `--require-smoke` and diff-scoped `security-audit`.
  *Enforced by:* `tests/test_brigade.py`, `tools/brigade/ship_prep.py`, `skills/edge-ship/SKILL.md`
- **[PAT-DELIVERY-ONE-WAY-BRAKE]** `classify_merge_danger` flags public API signature breaks, auth/security paths, `> 15` files, or `> 500` diff lines as One-Way Door PRs requiring human merge.
  *Enforced by:* `tests/test_refactor_receipt_and_ship.py`, `tools/brigade/ship_prep.py`
