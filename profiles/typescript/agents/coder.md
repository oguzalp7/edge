# Stack Overlay: TypeScript Coder (`typescript`)

1. **Compiler & Vitest Gate:**
   - Run `npx tsc --noEmit` inside the leased worktree: MUST exit `0`.
   - Run `npm run test:unit` (or scoped `npx vitest run`): MUST exit `0`.
2. **Type-System Discipline (`RULE-TS-*`):**
   - NEVER use `: any`, `<any>`, `as any`, `any[]`, `Array<any>`, `as unknown as <T>`, `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`, or non-null `!`.
   - Prefer `satisfies`, branded IDs, `z.infer<...>`, and exhaustive `switch` `default: never` guards.
   - Keep `Record<string, unknown>` at I/O boundaries only; avoid mixed status-boolean optional bags.
3. **Production Hygiene:**
   - Zero `console.log(...)` in shipped production modules (`src/`).
   - Zero `DEFAULT_*` or `MOCK_*` synthetic fallbacks in production code.
