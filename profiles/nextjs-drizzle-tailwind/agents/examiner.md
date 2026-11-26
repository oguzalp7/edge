# Stack Overlay: Next.js + Drizzle + Tailwind Examiner (`nextjs-drizzle-tailwind`)

1. **Axis 1 (Drizzle, Pure Tailwind & A11y Standards):**
   - Flag direct Drizzle `db.*` queries inside `src/actions/**`, `app/actions/**`, or `.tsx` files (`SQL_LEAK_PATTERN`).
   - Flag hardcoded `CANONICAL_*` arrays, raw `<th>` labels, shallow JSX wrappers (`SHALLOW_WRAPPER_PATTERN`), or external UI kits (shadcn/Radix).
2. **Axis 2 (Next.js Omission Gates):**
   - Flag missing `{ items, total, page, pageSize }` & URL `searchParams`, missing `safe-action.ts` / `UNIQUE` idempotency, missing `tenantId`/`orgId`/`ownerId` ABAC filters, missing `disabled={isPending}`, missing `!res.success` optimistic `rollback` + `revalidatePath`, missing `export const dynamic = "force-dynamic"`, `bg-white` without `dark:bg-*`, icon-only `<X>` missing `aria-label`, and leftover `DEFAULT_*`/`MOCK_*` fallbacks.
3. **Axis 3 (Gate & QA Evidence):**
   - Verify `tools/gate.py` (`MigrationGate`, `Layer Leakage`, `Zero-Wrapper`, `Domain Purity`, `Dual-Theme & A11y`) and `diff_image.py` (`<= 0.15%`) exited `0`.
