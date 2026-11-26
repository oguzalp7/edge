# Stack Overlay: Next.js + Drizzle + Tailwind Spec Writer (`nextjs-drizzle-tailwind`)

1. **7-Row Matrix Stack Bindings (`Next.js + Drizzle + Tailwind`):**
   - (1) **Value Sourcing:** UI Input / URL `searchParams` / Drizzle `src/db/schema/*` Table.Column / `src/core/` (zero `DEFAULT_*`/`MOCK_*`).
   - (2) **Pagination by Default:** `{ items, total, page, pageSize }` + URL `searchParams`.
   - (3) **Idempotency & Concurrency:** Drizzle `UNIQUE`/`ON CONFLICT`, state guard, or `idempotencyKey` (`safe-action.ts`) + `disabled={isPending}`.
   - (4) **Resource-Level AuthZ / ABAC:** `tenantId`/`orgId`/`ownerId` ownership filters beyond `requireAuth()`.
   - (5) **UI 4-State & Optimistic Rollback:** `Loading`, `Empty`, `No-Results`, `Error` + `!res.success` `rollback` + `bg-white`/`dark:bg-*` + `<X>` `aria-label`.
   - (6) **Cache Revalidation & Dynamic SSR:** `revalidatePath` on mutations + `export const dynamic = "force-dynamic"` on DB-reading App Router pages.
   - (7) **Superseded / Mock Deletion:** Delete `DEFAULT_*`/`MOCK_*` fallbacks, shallow wrappers, and orphan `.tsx` files in the same slice.
