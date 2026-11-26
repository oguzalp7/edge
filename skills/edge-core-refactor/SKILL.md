---
name: edge-core-refactor
profile: nextjs-drizzle-tailwind
description: Backend & Core architecture refactoring manual for isolated subagents. Guides the extraction of bloated Server Actions into thin controllers, extracting database queries into domain repositories (`src/lib/<domain>/repository.ts`), and isolating pure business logic into `src/core/` using Poteto's hillclimbing loop and deterministic verification gates.
---

# 🧠 /edge-core-refactor — Backend & Core Architecture Refactoring Manual

> **Stack Profile:** `nextjs-drizzle-tailwind` — see [`profiles/nextjs-drizzle-tailwind/PLAYBOOK.md`](../../profiles/nextjs-drizzle-tailwind/PLAYBOOK.md).

> *"Break monolithic systems by carving deep boundaries at the natural seams. Thin down controllers to mere coordinators, push pure domain rules into hermetic modules, and isolate database queries into focused repositories. One debt item per iteration, verified deterministically."* — **Poteto's Hillclimbing Protocol & Matt Pocock's Seam Principles**

This skill guides a bounded, single-purpose subagent through extracting bloated, mixed-concern Server Actions into clean, layered architecture:
- **Thin Controllers:** `src/actions/<domain>.ts` (orchestration, validation, auth verification only)
- **Domain Repositories:** `src/lib/<domain>/repository.ts` (Drizzle ORM queries, inserts, transactions)
- **Pure Domain Cores:** `src/core/<domain>/` (in-memory business rules, calculation engines, scheduling algorithms)

---

## 🏛️ Target Clean Architecture Model

```
                    ┌────────────────────────────┐
                    │ Client / UI Components     │
                    └─────────────┬──────────────┘
                                  │ RPC / Form Action
                                  ▼
                    ┌────────────────────────────┐
                    │ Server Action (Controller) │ <─── src/actions/<domain>.ts
                    │ (Validation, Auth, Coord)  │      (Layer Leakage Gate & Max CC Non-Regression)
                    └───────┬────────────┬───────┘
                            │            │
            Domain Queries  │            │ Pure Domain Rules
                            ▼            ▼
 ┌─────────────────────────────┐      ┌─────────────────────────────┐
 │ Domain Repository           │      │ Domain Core Engine          │
 │ src/lib/<domain>/repository │      │ src/core/<domain>/          │
 └──────────────┬──────────────┘      └─────────────────────────────┘
                │ SQL / Drizzle
                ▼
 ┌─────────────────────────────┐
 │ Frozen Database Schema      │ <─── src/db/schema/* & drizzle/
 │ (MigrationGate: UNTOUCHABLE)│      (Modifications strictly forbidden!)
 └─────────────────────────────┘
```

---

## 🛑 Strict Guardrails & Safety Invariants

Every refactoring iteration MUST adhere to all 5 non-negotiable architectural invariants:

1. **MigrationGate Invariant (Zero Schema Changes):**
   - **NEVER** modify or touch files under `src/db/schema/*` or `drizzle/` migrations.
   - Refactoring tasks must NEVER alter database schemas, columns, constraints, or table structures.
   - Any diff touching migration or schema files will be immediately rejected at Stage 1 of the Verification Gate.

2. **Layer Leakage Gate (Controller DB Leak Non-Regression):**
   - Action controllers (`src/actions/**`, `app/actions/**`, `*/actions/*.ts*`) must never introduce new direct `db.select`, `db.insert`, `db.update`, `db.delete`, `db.transaction`, or `db.query` calls (`after_leaks <= before_leaks`).
   - Brand-new action controllers must have **zero** (`0`) direct DB calls.
   - Actions must delegate persistence strictly to domain repositories (`src/lib/<domain>/repository.ts`).

3. **Max CC Non-Regression Gate (Complexity Ceiling, Not Line Contraction):**
   - Artificial line-count reduction rules (`ΔSLOC < 0`) are retired: legitimate layer extractions (TypeScript interfaces, domain repositories, pure core functions) may naturally add net lines.
   - Instead, cyclomatic complexity must never regress on modified production files:
     $$\text{CC}_{\text{after}} \le \max(\text{CC}_{\text{before}}, 10)$$
   - Newly created production files must strictly maintain a healthy per-function complexity ceiling ($\text{CC}_{\text{after}} \le 10$).

4. **Zero-Wrapper Left Behind (No Shallow Pass-Throughs):**
   - Do not create shallow pass-through services, 1-line re-exports, or redundant abstraction layers.
   - Every module must represent a **Deep Module** (Ousterhout): simple interface hiding substantive implementation details.

5. **Poteto Hillclimbing Prensibi (1 Borç = 1 Mikro-Commit):**
   - Focus on **1 specific debt item** from `.edge/ledger/core.json` per subagent iteration.
   - Ensure strictly monotonic debt improvement:
     $$\text{Debt}_{t+1} < \text{Debt}_t$$
   - Never batch multiple unrelated refactorings into a single branch.

---

## 🔄 The 6-Step Execution Protocol

```
1. Target Isolation ──> 2. Characterization Test ──> 3. MigrationGate Assertion
         │
         └───> 4. Strangler Fig Extraction ──> 5. Hermetic Verification ──> 6. Gate & Ledger Update
```

### Step 1: Target Identification & Branch Isolation
1. Inspect `.edge/ledger/core.json` to find the highest-priority debt item (e.g. `RULE-ACTION-DB-LEAK` or `RULE-FAT-FUNCTION`).
2. Identify the target action file (e.g. `src/actions/appointments.ts`) and target operation.
3. Create and switch to an isolated refactor branch:
   ```bash
   git checkout -b refactor/core-<domain>-<operation>
   # Example: git checkout -b refactor/core-appointments-create
   ```

### Step 2: Characterization Test Seam
Before altering any production code, verify or construct an in-memory characterization test to lock in existing behavioral contracts:
1. Check if tests exist in `tests/unit/<domain>.test.ts`.
2. If missing, write a characterization test asserting the inputs, outputs, and edge cases of the action:
   ```typescript
   // tests/unit/appointments.test.ts
   import { describe, it, expect, vi } from "vitest";
   import { createAppointmentAction } from "@/actions/appointments";

   describe("createAppointmentAction characterization seam", () => {
     it("validates required payload fields and dispatches correctly", async () => {
       const result = await createAppointmentAction({ ... });
       expect(result.success).toBe(true);
     });
   });
   ```
3. Run the unit test to verify it passes against baseline behavior:
   ```bash
   npm run test:unit
   ```

### Step 3: MigrationGate Assertion
Assert that the working directory and base commit are completely free of pending schema modifications:
```bash
git diff --name-only HEAD~1
```
Confirm no files matching `src/db/schema/*` or `drizzle/*` are present.

### Step 4: Strangler Fig Extraction
Refactor the action using the Strangler Fig approach:

1. **Extract Database Queries to Domain Repository:**
   Create or update `src/lib/<domain>/repository.ts`:
   ```typescript
   // src/lib/appointments/repository.ts
   import { db } from "@/db";
   import { appointments } from "@/db/schema";
   import { eq } from "drizzle-orm";

   export interface AppointmentRepository {
     findById(id: string): Promise<Appointment | null>;
     create(data: NewAppointment): Promise<Appointment>;
   }

   export const appointmentRepository: AppointmentRepository = {
     async findById(id: string) {
       const [record] = await db.select().from(appointments).where(eq(appointments.id, id));
       return record ?? null;
     },
     async create(data: NewAppointment) {
       const [created] = await db.insert(appointments).values(data).returning();
       return created;
     },
   };
   ```

2. **Extract Pure Business Logic to Domain Core (if applicable):**
   If the action contains date calculations, conflict checks, or state transitions, move them to `src/core/<domain>/`:
   ```typescript
   // src/core/appointments/conflict.ts
   export function hasTimeConflict(
     existingStart: Date,
     existingEnd: Date,
     requestedStart: Date,
     requestedEnd: Date
   ): boolean {
     return requestedStart < existingEnd && requestedEnd > existingStart;
   }
   ```

3. **Thin the Server Action (Controller):**
   Replace inline database queries with calls to the domain repository and core logic:
   ```typescript
   // src/actions/appointments.ts
   import { appointmentRepository } from "@/lib/appointments/repository";
   import { hasTimeConflict } from "@/core/appointments/conflict";

   export async function createAppointmentAction(formData: AppointmentInput) {
     // 1. Validate payload
     const validated = validateInput(formData);
     // 2. Delegate to repository / core
     const conflict = await appointmentRepository.findOverlapping(...);
     if (conflict) {
       return { success: false, error: "Slot already reserved" };
     }
     const created = await appointmentRepository.create(validated);
     return { success: true, data: created };
   }
   ```

### Step 5: Hermetic Verification
Execute full compiler and unit test checks to guarantee zero behavioral or type regressions:
```bash
# 1. Zero TypeScript errors
npx tsc --noEmit

# 2. All unit tests must pass
npm run test:unit
```
If any compilation or test failure occurs, revert and fix immediately before continuing.

### Step 6: Edge Verification Gate, 4-Seal `RefactorReceipt` & Ledger Update
1. **Run Edge Verification Gate (`--format json`):**
   Run the deterministic verification gate (`MigrationGate` + `Max CC Non-Regression` + `Layer Leakage Gate` + `Differential SDL`):
   ```bash
   python3 tools/gate.py <repo_path> --base HEAD~1 --track core --format json
   ```
   Missing analyzers (such as `tree-sitter`) emit `null` for `dryer_clones` — never `0`.

2. **Seal 4-Seal `RefactorReceipt` & Verify Ledger Status:**
   ```bash
   python3 tools/brigade/cli.py seal-refactor <repo_path> --base <integration_branch>  # e.g. development
   python3 tools/radar/cli.py status <repo_path>
   ```
   Ensure the 4-seal receipt at `.edge/receipts/refactor/<slug>.{json,md}` passes `RefactorReceiptVerifier` (`commit_sha`, `changed_files_hash`, non-null `metric_targets`, `ExaminerReceipt PASS` with distinct `examiner_cid != surgeon_cid`).

3. **Commit & Submit:**
   Create a clean, atomic micro-commit following Conventional Commits:
   ```bash
   git add src/actions/<domain>.ts src/lib/<domain>/repository.ts src/core/ tests/
   git commit -m "refactor(core): extract <operation> from <domain> action to repository and pure core"
   ```
   Report the commit hash and ledger delta back to the coordinator agent.
