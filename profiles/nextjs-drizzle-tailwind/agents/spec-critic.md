# Stack Overlay: Next.js + Drizzle + Tailwind Spec Critic (`nextjs-drizzle-tailwind`)

1. **Zero-Decision Audit (Next.js / Drizzle / Tailwind):**
   - Flag missing `{ items, total, page, pageSize }` & URL `searchParams` pagination contracts.
   - Flag missing mutation idempotency (`safe-action.ts`, Drizzle `UNIQUE`/`ON CONFLICT`, `disabled={isPending}`).
   - Flag missing resource-level ABAC (`tenantId`/`orgId`/`ownerId`) beyond `requireAuth()`.
   - Flag missing UI 4-state (`Loading`/`Empty`/`No-Results`/`Error`), missing `!res.success` optimistic `rollback`, missing `revalidatePath` + `export const dynamic = "force-dynamic"`, `bg-white` without `dark:bg-*`, or unscheduled `DEFAULT_*`/`MOCK_*` and orphan `.tsx` cleanup.
