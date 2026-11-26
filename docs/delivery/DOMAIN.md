# Domain: delivery

- **Owner / DRI:** @edge-delivery
- **Concepts:** `two-tier-delivery`, `refactor-receipt-binding`, `one-way-door-brake`

## Living Invariants
- **[INV-DELIVERY-DEV-FIRST]** Slice delivery targets the integration branch by default and blocks direct slice-to-staging promotion without an explicit topology override.
- **[INV-DELIVERY-RECEIPT-BINDING]** Refactor pull requests require a valid, non-stale refactor receipt cryptographically bound to the target commit and changed-file hash.
- **[INV-DELIVERY-LEAN-PR]** Shipped pull request bodies stay bounded to a 1-Minute Briefing summary, verified evidence sections, and scoped issue links.
- **[INV-DELIVERY-PARENT-SAFE]** Pull request footers auto-close only child execution issues (`Closes #<child>`) and reference parent specification epics without auto-closing the parent.

## Adopted Patterns
- **[PAT-DELIVERY-TWO-TIER]** Per-spec branches integrate before consolidated release promotion gated by route smoke and security audits.
- **[PAT-DELIVERY-ONE-WAY-BRAKE]** Public interface breaks, authentication paths, and oversized diffs trigger One-Way Door brakes requiring explicit human merge confirmation.
