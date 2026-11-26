# Stack Overlay: Next.js + Drizzle + Tailwind Seam Architect (`nextjs-drizzle-tailwind`)

1. **Repository & Server Action Seams:**
   - Declare `src/lib/<domain>/repository.ts` interfaces and `src/core/<domain>/` pure types decoupled from Drizzle `db` clients and Next.js runtime globals.
2. **4 Mandatory Negative RED Tests (Next.js / Drizzle):**
   - (1) **Idempotency / Duplicate Call:** Duplicate Server Action / `safe-action.ts` invocation returns deterministic conflict/no-op.
   - (2) **Pagination Bounds:** Enforces `{ items, total, page, pageSize }` and bounded `searchParams` clamping.
   - (3) **ABAC & Validation Fail-Fast:** Rejects unauthorized `tenantId`/`orgId`/`ownerId` scope and invalid Zod/UUID payloads.
   - (4) **Failure Rollback & Cache Invalidation:** Asserts `{ success: false }` triggers optimistic state `rollback` and `revalidatePath` invocation on mutation.
