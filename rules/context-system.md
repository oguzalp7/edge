# Edge Context System v1.0 — Reference Constitution

Authoritative specification for the **Context System** pillar of Edge repositories.

---

## 1. The System Triad

Edge separates engineering context into three orthogonal pillars:
- **Design System:** Visual tokens, component primitives, and UI layout contracts.
- **Program System:** Executable code, deterministic gates, tests, and runtime state machines.
- **Context System:** Machine- and human-readable domain ontology (`CONTEXT.md` + `docs/<domain>/DOMAIN.md`), minimal code frontmatter, and bounded briefing rituals.

---

## 2. Diátaxis Mode Separation

Every document MUST belong to exactly one Diátaxis quadrant; never mix modes in the same file:
- **Reference:** Neutral, present-tense facts (`CONTEXT.md`, `docs/<domain>/DOMAIN.md`, `rules/context-system.md`). Updated in place.
- **How-To Guide:** Task-oriented operational steps (`skills/*/SKILL.md`, `rules/*.md`).
- **Explanation:** Architectural rationale and historical evolution (lives in `git log` and archived 1-spec-1-PR history, never inside `DOMAIN.md`).
- **Tutorial:** Guided onboarding (human-only; skipped by execution agents).

---

## 3. 3-Layer Dependency Inversion (`DOMAIN.md` $\rightarrow$ `CONTEXT.md` $\leftarrow$ Code/Tests)

1. **`docs/<domain>/DOMAIN.md` (100% Code-Free Abstract Behavioral Law — Reference):**
   - Header metadata uses ONLY `# Domain: <name>` (`domains` rejected), `- **Owner / DRI:**`, and `- **Concepts:** <closed IDs from CONTEXT.md>`. Omit `- **Paths:**` and `*Enforced by:*`.
   - Body defines `## Living Invariants` (`- **[INV-<DOM>-<ID>]**`) and `## Adopted Patterns` (`- **[PAT-<DOM>-<ID>]**`), plus optional 5–10 line `mermaid` or `pseudo` / `pseudocode` blocks where flow/precedence benefits.
   - **`CODE_LEAK_IN_DOMAIN_DOC` (`ERROR`):** Deterministic ontology check forbids file paths, code extensions, `*Enforced by:*`, executable/bare/tilde/unclosed fences, function calls, and backticked code identifiers (`snake_case`, `camelCase`, `PascalCase`, dotted members) inside `DOMAIN.md`.
   - Legacy `docs/domains/<domain>.md` remains readable for backward compatibility.
2. **`CONTEXT.md` (Single Code Bridge — Repo Root Reference):**
   - `## Domain Map` is the canonical SSOT for `Domain -> Path Globs` (`DOMAIN.md` `Paths:` is used only as fallback if `CONTEXT.md` lacks an entry).
   - `## Closed Concept Glossary` is the sole bridge mapping kebab-case concept IDs to exact code symbols and files.
3. **Code & Test Files (Bottom-Up Anchors via `invariant_index`):**
   - Directory globs in `CONTEXT.md` assign domain ownership automatically (files omit `@domain` unless overriding).
   - Code and test headers point UP via `@intent`, `@concepts`, and `@invariants [INV-*]`; `validate_ontology()` builds `OntologyReport.invariant_index` across tracked code and `tests/**` (without running `LEGACY_TAG` checks on `tests/**`).

---

## 4. Minimal 1–3 Line Code Frontmatter

Only the leading header block (top 30 lines, stopping at the first executable code line after shebang, coding cookie, or `"use client"` / `"use strict"`) is scanned by `validate_ontology()`:
- **Allowed Tags:**
  - `@intent <1-line module boundary>`
  - `@concepts <comma-separated closed IDs from CONTEXT.md>`
  - `@invariants <[INV-*] IDs enforced by this file>`
- **Banned Legacy Tags:**
  - `ERROR`: `@inputs`, `@outputs`, `@glossary`, `@route`, `@spec`, `@base_commit`, `@domain_jargon`
  - `WARNING`: `@module` (retained as warning for JSDoc compatibility)

---

## 5. Intake & Briefing Contracts

- **Phase 0 (`grill-with-docs`):** Lock new domain boundaries and closed kebab-case concepts into `CONTEXT.md` before Phase 1 INVEST vertical slicing.
- **4-Line Commander Decision Card (`/edge-distill`):** Proposals render as *What failed / 1-line rule diff / Real risk if rejected / Possible conflict* (`REJECT` if unclear).
- **1-Minute Briefing (`/edge-ship` & `/edge-technical-writing`):** Executive summary covering *What changed*, *Why*, *Risk / Blast radius*, and *Verification evidence* with verified counts.
