# Stack Overlay: Next.js + Drizzle + Tailwind Coder (`nextjs-drizzle-tailwind`)

1. **Server Actions & Repository Layering:**
   - Keep `src/actions/**` / `app/actions/**` thin (validation, `requireAuth()`, ABAC `tenantId`/`orgId`/`ownerId`, `idempotencyKey`/`safe-action.ts`).
   - Place all Drizzle `db.*` queries/transactions in `src/lib/<domain>/repository.ts` and pure logic in `src/core/<domain>/` (`0` `DEFAULT_*`/`MOCK_*` fallbacks).
   - Default list endpoints to `{ items, total, page, pageSize }` + URL `searchParams`.
2. **UI, SSR & Cache Invalidation:**
   - Lock in-flight controls with `disabled={isPending}`; on `!res.success` roll back optimistic state (`rollback`) and show a visible error.
   - Export `export const dynamic = "force-dynamic"` on DB-reading App Router pages/layouts and invoke `revalidatePath` on mutations.
3. **Pure Tailwind Dual-Theme & A11y:**
   - Pair `bg-white` with `dark:` (`dark:bg-*`), provide descriptive `aria-label` on icon-only `<X>` buttons, and bind `<label>` to form inputs.
   - Use pure Tailwind + `src/components/ui/` primitives (zero shadcn/Radix/DaisyUI, zero hardcoded `CANONICAL_*` or raw `<th>` in JSX).
