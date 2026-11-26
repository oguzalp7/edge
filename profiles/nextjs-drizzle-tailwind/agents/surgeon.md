# Stack Overlay: Next.js + Drizzle + Tailwind Surgeon (`nextjs-drizzle-tailwind`)

1. **Core & UI Extraction Targets:**
   - Extract raw Drizzle `db.*` queries from `src/actions/**` / `app/actions/**` into `src/lib/<domain>/repository.ts` (`0` action leaks) and pure logic into `src/core/<domain>/`.
   - Consolidate duplicate pure Tailwind JSX into `src/components/ui/` and `git rm` shallow wrappers (`Zero-Wrapper`) + `DEFAULT_*`/`MOCK_*` fallbacks.
2. **Preserve Next.js, SSR & A11y Invariants:**
   - Preserve `disabled={isPending}` locks, `!res.success` optimistic `rollback`, `export const dynamic = "force-dynamic"`, `revalidatePath`, `bg-white` + `dark:bg-*`, `<X>` `aria-label`, and `<label>` bindings.
3. **`MigrationGate` (Drizzle Lock):**
   - NEVER touch `src/db/schema/*` or `drizzle/*` on refactor tracks.
