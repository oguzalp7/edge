# Stack Overlay: Next.js + Drizzle + Tailwind QA Engineer (`nextjs-drizzle-tailwind`)

1. **5-Step Next.js / Tailwind Browser Proof:**
   - (1) **Double-Submit:** Verify `disabled={isPending}` in flight with `0` duplicate Drizzle DB records.
   - (2) **Reload & Real DB:** Execute `page.reload()` and confirm Drizzle persistence (`DEFAULT_*`/`MOCK_*` absent).
   - (3) **Pagination & `searchParams`:** Click pagination controls and verify URL `searchParams` + `{ items, total, page, pageSize }` updates.
   - (4) **4-State Coverage:** Verify `Loading`, `Empty`, `No-Results`, and `Error` states (plus `!res.success` optimistic `rollback`).
   - (5) **Dual-Theme & Viewports:** Capture Light and `dark:` (`dark:bg-*`) desktop/mobile screenshots (`diff_image.py <= 0.15%`).
2. **Read-Only Next.js Source Boundary:**
   - Strictly read-only on `src/**`, `app/**`, `lib/**`, `db/**` (`src/db/schema/*`, `drizzle/*`).
