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
- **Explanation:** Architectural rationale and historical evolution (lives in `git log` or ADR notes, never inside `DOMAIN.md`).
- **Tutorial:** Guided onboarding (human-only; skipped by execution agents).

---

## 3. Physical Ontology (`CONTEXT.md` + `docs/<domain>/DOMAIN.md`)

1. **`CONTEXT.md` (Repo Root — Reference):**
   - Contains `## Domain Map` (domain-to-glob index) and `## Closed Concept Glossary` (canonical kebab-case concept IDs mapped to exact code symbols/files).
   - `DOMAIN.md` `Paths:` is canonical; any mismatch with `CONTEXT.md` emits a `GLOB_MISMATCH` warning.
2. **`docs/<domain>/DOMAIN.md` (Canonical Domain Deed / Tapu — Reference):**
   - Required header & metadata:
     - `# Domain: <name>` (`domains` is reserved/rejected so `docs/domains/DOMAIN.md` never collides)
     - `- **Paths:** <comma-separated tracked globs>`
     - `- **Owner / DRI:** <handle or team>`
     - `- **Concepts:** <comma-separated closed IDs from CONTEXT.md>`
   - Bullet-defined invariants and patterns:
     - `- **[INV-<DOM>-<ID>]** <Single-line rule>` followed by `  *Enforced by:* <repo-relative file/test paths>`
     - `- **[PAT-<DOM>-<ID>]** <Adopted pattern>`
   - Legacy `docs/domains/<domain>.md` remains readable for backward compatibility; canonical `docs/<domain>/DOMAIN.md` takes precedence.
3. **Filetree = Domain by Convention:**
   - Directory globs in `DOMAIN.md` assign ownership automatically. Files omit `@domain` unless acting as a cross-cutting override.

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
