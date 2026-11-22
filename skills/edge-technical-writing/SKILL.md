---
name: edge-technical-writing
description: Context-System technical writing and executive briefing skill. Enforces Diataxis mode separation, single-term real-symbol discipline, 1-Minute Briefings, and self-verifying counts without language-specific grammar bloat.
disable-model-invocation: true
---

# /edge-technical-writing — Context-System Documentation & Briefings

Authoritative How-To guide for writing `CONTEXT.md`, `docs/<domain>/DOMAIN.md`, PR summaries, and executive briefings across any repository language (Turkish or English).

---

## 1. Diátaxis Mode Separation

Assign every document to **one** quadrant before writing; never mix quadrants inside one file:
- **Reference:** Neutral, present-tense facts (`CONTEXT.md`, `docs/<domain>/DOMAIN.md`, `rules/context-system.md`). Update in place; history stays in `git log`.
- **How-To Guide:** Task-oriented steps (`skills/*/SKILL.md`, runbooks). Omit tutorials and design history.
- **Explanation:** Architectural trade-offs and "why" rationale (`git log` and archived 1-spec-1-PR history). Keep out of `DOMAIN.md`.
- **Tutorial:** Guided learning for humans; omit from agent-facing specs.

---

## 2. Single-Term & Real-Symbol Discipline

- **Closed Glossary Lock:** Use only canonical kebab-case concept IDs registered in `CONTEXT.md` (`## Closed Concept Glossary`). Never invent synonyms for existing terms.
- **Real Symbols Only:** Cite exact file paths, class/function names, and CLI flags observed in the codebase. Never cite planned or remembered symbols.
- **Zero Grammar Bloat:** Focus on structural clarity, short scannable lines, and verified facts—not English-only prose style rules.

---

## 3. 1-Minute Briefing (60-Second Executive Format)

Use for **PR Summaries** (`/edge-ship`), **Distill Reviews** (`/edge-distill`), and **On-Demand Executive Briefs**:

```markdown
### 1-Minute Briefing
- **What changed:** <1-line scope + verified file/slice count>
- **Why:** <1-line problem or invariant closed>
- **Risk / Blast Radius:** <One-Way vs Two-Way door + affected domain(s)>
- **Verification:** <exact command(s) and observed pass/fail counts>
```

Keep briefings under 8 lines so a human Commander or Reviewer grasps intent, risk, and proof in 60 seconds.

---

## 4. Self-Verifying Counts & Pre-Publish Checklist

Before finalizing any document or briefing:
1. Run `rg`, `wc -l`, or `python3 tools/drift/cli.py check . --ontology-only` to verify every file path, line count, and test count cited.
2. Confirm `DOMAIN.md` `Paths:` match `CONTEXT.md` `## Domain Map` identically (`0` `GLOB_MISMATCH` warnings).
3. Confirm every `*Enforced by:*` file exists on disk and every `@concepts` / `@invariants` tag resolves cleanly.
