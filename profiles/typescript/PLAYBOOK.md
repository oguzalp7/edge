# TypeScript Stack Profile Playbook (`typescript`)

Base TypeScript & Vitest profile (`extends: []`, framework-, ORM-, and CSS-agnostic). Suitable for Node/TS services, CLI tools, and shared hosting / MySQL / MSSQL backends.

## 1. Hermetic Verification Commands
- **Typecheck:** `npx tsc --noEmit` MUST exit `0`.
- **Unit Tests:** `npm run test:unit` (or scoped `npx vitest run <file>`) MUST exit `0`.

## 2. Type-System Discipline (`tools/audit/cli.py --track types`)
- **Zero Type Escapes (`TYPE_ESCAPE_PATTERN`, `TS_EXPLICIT_ANY_PATTERN`):** Forbid `: any`, `<any>`, `as any`, `any[]`, `Array<any>`, `as unknown as <T>`, `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`, and postfix non-null `!`.
- **Preferred Patterns:** Use `satisfies`, branded domain IDs (`readonly __brand`), schema inference (`z.infer<...>`), and exhaustive `switch` `default:` branches bound to `: never`.
- **Domain Purity:** Keep `Record<string, unknown>` at external I/O perimeters only; avoid mixed status-boolean optional bags and long positional `*Id: string` signatures.

## 3. Production Hygiene & Test Isolation (`edge-tests-audit-typescript`)
- **No Shipped `console.log` (`TS_CONSOLE_LOG_PATTERN`):** Remove debug `console.log(...)` calls from production `src/` files; use structured logging or explicit return values.
- **Unit Test Purity (`tests/unit/`):** Keep unit tests hermetic and in-memory (`vi.mock`, `vi.fn`, `vi.spyOn`). Isolate live database/network tests (MySQL, MSSQL, external APIs) under `tests/integration/` with deterministic `afterAll` cleanup.

## 4. Delivery Topology (`single_main`)
- Default integration branch is `main` (`git merge --ff-only` from leased worktrees). Customize via `.edge/brigade.json` `"stage_branches"` if the repository uses another branch name.
