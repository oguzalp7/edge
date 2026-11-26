# Stack Overlay: Next.js + Drizzle + Tailwind Researcher (`nextjs-drizzle-tailwind`)

1. **4-Item Next.js / Drizzle Seam & Omission Inventory:**
   - (1) **Pagination:** Verify `{ items, total, page, pageSize }` envelopes and URL `searchParams` propagation.
   - (2) **ABAC & AuthZ Scope:** Map `tenantId`/`orgId`/`ownerId` ownership checks across `src/actions/**` and `src/lib/*/repository.ts`.
   - (3) **Idempotency Seam:** Locate `safe-action.ts`, Drizzle `UNIQUE`/`ON CONFLICT` constraints, and mutation retry guards.
   - (4) **Mock & Orphan Inventory:** Flag `DEFAULT_*`/`MOCK_*` fallbacks, raw `db.*` leaks in actions/JSX, dead helpers, and orphan `.tsx` components with `file:line`.
2. **Migration Path Discovery:**
   - Inspect `drizzle.config.*`, `src/db/schema/*`, and `drizzle/*` before proposing repository seams.
