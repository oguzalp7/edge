# Stack Overlay: TypeScript Seam Architect (`typescript`)

1. **Strict TypeScript Contracts:**
   - Declare explicit `interface` / `type` signatures, discriminated result unions, and branded domain IDs before writing tests.
   - Avoid wide `any`, `Record<string, unknown>` inside pure domain interfaces, and long positional `*Id: string` parameter lists.
2. **Hermetic Vitest RED Tests:**
   - Author RED unit/contract tests in `tests/unit/` (or `**/*.test.ts*`) using `vi.mock`, `vi.fn`, or in-memory repository seams.
   - Never import live database clients or run uncontained DDL/DML seeds inside unit tests.
   - Verify `npx tsc --noEmit` resolves contract types cleanly and the RED tests fail on assertion behavior, not syntax errors.
