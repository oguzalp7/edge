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

## 2. Dependency Inversion, Single-Term & Real-Symbol Discipline

- **3-Layer Dependency Inversion:** Keep `docs/<domain>/DOMAIN.md` 100% code-free (`Owner / DRI:` + `Concepts:` only, zero paths/extensions/`*Enforced by:*`, optional concise `mermaid` or `pseudo`/`pseudocode` blocks without paths); keep all glob and symbol mapping in `CONTEXT.md`; point code/tests UP via `@intent` / `@concepts` / `@invariants` (indexed into `invariant_index`).
- **Closed Glossary Lock & Zero Code Leaks:** Use only canonical kebab-case concept IDs from `CONTEXT.md`. Never put executable fences, function calls, or `snake_case`/`camelCase`/`PascalCase`/dotted identifiers inside `DOMAIN.md` (`CODE_LEAK_IN_DOMAIN_DOC`).
- **Real Symbols Only (in `CONTEXT.md`, PRs & How-Tos):** Cite exact verified paths, symbols, and CLI flags—never planned or guessed names, and zero English-only grammar bloat.

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
2. Confirm `CONTEXT.md` `## Domain Map` owns domain globs (`0` `GLOB_MISMATCH` warnings) and `DOMAIN.md` triggers `0` `CODE_LEAK_IN_DOMAIN_DOC` errors.
3. Confirm `@concepts` and `@invariants` header tags in code/tests populate `invariant_index` cleanly without unknown references.
