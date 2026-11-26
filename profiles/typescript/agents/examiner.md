# Stack Overlay: TypeScript Examiner (`typescript`)

1. **Axis 1 (Type-System & Hygiene Audit):**
   - Flag any `: any`, `as any`, `as unknown as`, `@ts-ignore`, `@ts-expect-error`, `@ts-nocheck`, postfix `!`, or shipped `console.log(...)`.
   - Verify `--track types` discipline (`satisfies`, exhaustive `switch` `: never`, no `Record<string, unknown>` inside pure domain logic).
2. **Axis 3 (Compilation & Test Evidence):**
   - Require `npx tsc --noEmit` exit `0` and `npm run test:unit` (Vitest) exit `0`; timed-out or skipped checks are `FAIL`.
   - Confirm unit tests under `tests/unit/` remain hermetic (no live DB/network I/O leaks).
