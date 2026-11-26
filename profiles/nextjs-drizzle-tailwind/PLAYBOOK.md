# Next.js + Drizzle + Tailwind Stack Profile Playbook (`nextjs-drizzle-tailwind`)

Full-stack preset extending `typescript` with Next.js App Router, Drizzle ORM `MigrationGate`, Server Action -> Repository layering, pure Tailwind dual-theme/Lucide a11y, and Coolify two-tier delivery (`development -> staging -> production`).

## 1. Next.js App Router & Server Actions
- **Thin Controllers (`src/actions/**`, `app/actions/**`, `*/actions/*.ts*`):** Validate input, enforce `requireAuth()` + resource ABAC (`tenantId`/`orgId`/`ownerId`), guard mutation idempotency (`safe-action.ts`, DB `UNIQUE`/`ON CONFLICT`, `idempotencyKey`), and call `revalidatePath(...)` on mutations.
- **Dynamic SSR & Pagination:** Export `export const dynamic = "force-dynamic"` on DB-reading App Router pages/layouts. Default list queries to `{ items, total, page, pageSize }` + URL `searchParams`.
- **Submit Lock & Optimistic Rollback:** Lock in-flight UI controls with `disabled={isPending}`; on `!res.success` roll back optimistic state (`rollback`) and surface a visible error.

## 2. Drizzle ORM & `MigrationGate`
- **Layer Leakage (`SQL_LEAK_PATTERN`):** Isolate all `db.select`, `db.insert`, `db.update`, `db.delete`, `db.transaction`, and `db.query` calls inside `src/lib/<domain>/repository.ts` (`0` direct `db.*` calls in Server Actions or `.tsx` files).
- **`MigrationGate`:** Refactor tracks NEVER touch `src/db/schema/*` or `drizzle/*` (auto-resolved via `drizzle.config.*` / `AGENTS.md`). Feature slices require `allow_schema_migration: true` for schema edits.
- **Pure Domain Cores:** Extract date/state/pricing logic into `src/core/<domain>/` with `0` DB imports and `CC <= 10` per new file.

## 3. Pure Tailwind Dual-Theme, Lucide A11y & Zero-Wrapper UI
- **Pure Tailwind Only (`src/components/ui/`):** Never add external UI component libraries (no shadcn, Radix, Bootstrap, DaisyUI). Delete shallow pass-through wrappers (`SHALLOW_WRAPPER_PATTERN`, `git rm`).
- **Domain Purity (`RAW_TH_PATTERN`, `CANONICAL_ARRAY_PATTERN`):** Never hardcode `CANONICAL_*` arrays or static `<th>` table headers in JSX; source domain terms from server/DB dictionaries.
- **Dual-Theme & A11y (`BG_WHITE_NO_DARK_PATTERN`, `ICON_X_BUTTON_NO_ARIA_PATTERN`):** Pair every `bg-white` with `dark:` (`dark:bg-*`), give every icon-only `<X>` button a descriptive `aria-label`, bind `<label>` to inputs, and keep `diff_image.py <= 0.15%`.

## 4. Coolify Two-Tier Delivery (`development -> staging -> production`)
- **Tier 1 (`1 Spec = 1 PR -> development`):** Slice worktrees land fast-forward (`git merge --ff-only`) or via per-spec `ship/<slug>` PRs into `development`.
- **Tier 2 (`Release PR: development -> staging`):** Run `smoke-routes` + diff-scoped `security-audit`, then `prepare-ship . --base staging --require-smoke`; merging `development -> staging` triggers Coolify deployment before promoting `staging -> production`.
