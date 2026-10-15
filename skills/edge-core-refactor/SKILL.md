---
name: edge-core-refactor
description: Backend & Core architecture refactoring manual for isolated subagents. Guides the extraction of bloated Server Actions into thin controllers, extracting database queries into domain repositories (`src/lib/<domain>/repository.ts`), and isolating pure business logic into `src/core/` using Poteto's hillclimbing loop and deterministic verification gates.
---

# 🧠 /edge-core-refactor — Backend & Core Architecture Refactoring Manual

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
                    │ (Validation, Auth, Coord)  │      (Target Contraction: ΔSLOC < 0)
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

Every refactoring iteration MUST adhere to all 6 non-negotiable architectural invariants:

1. **MigrationGate Invariant (Zero Schema Changes):**
   - **NEVER** modify or touch files under `src/db/schema/*` or `drizzle/` migrations.
   - Refactoring tasks must NEVER alter database schemas, columns, constraints, or table structures.
   - Any diff touching migration or schema files will be immediately rejected at Stage 1 of the Verification Gate.

2. **Database Leak Elimination:**
   - **Zero** direct `db.select`, `db.insert`, `db.update`, `db.delete`, or `db.transaction` calls inside `src/actions/`.
   - Actions must delegate persistence strictly to domain repositories (`src/lib/<domain>/repository.ts`).
   - Leaking raw SQL/Drizzle calls into the controller layer violates separation of concerns and fails automated audit.

3. **Target File Contraction ($\Delta\text{SLOC}_{\text{target}} < 0$):**
   - The target action file being refactored must strictly shrink:
     $$\Delta\text{SLOC}_{\text{target}} = \text{Insertions} - \text{Deletions} < 0$$
   - Controllers must become lean dispatchers. Any refactoring where the target action expands or stays neutral will fail the Target SLOC Contraction Gate.

4. **Scaffolding Budget Tolerance:**
   - When establishing a **new** domain repository (`src/lib/<domain>/repository.ts`), a one-time allowance up to **+25 lines** is permitted for repository interface and factory setup (`--allow-scaffolding 25`).
   - Subsequent extractions in that domain must maintain net non-inflation across production code ($\Delta\text{SLOC} \le 0$).

5. **Zero-Wrapper Left Behind (No Shallow Pass-Throughs):**
   - Do not create shallow pass-through services, 1-line re-exports, or redundant abstraction layers.
   - Every module must represent a **Deep Module** (Ousterhout): simple interface hiding substantive implementation details.

6. **Poteto Hillclimbing Prensibi (1 Borç = 1 Mikro-Commit):**
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

### Step 6: Edge Verification Gate & Ledger Update
1. **Run Edge Verification Gate:**
   Run the deterministic verification gate with target file contraction and applicable scaffolding allowance:
   ```bash
   # For existing repository updates:
   python3 tools/gate.py /home/oguz/MS-Randevu-monolith --base HEAD~1 --target-file src/actions/<domain>.ts

   # For brand-new domain repository creation (with scaffolding allowance):
   python3 tools/gate.py /home/oguz/MS-Randevu-monolith --base HEAD~1 --target-file src/actions/<domain>.ts --allow-scaffolding 25
   ```

2. **Verify Ledger Status & Hillclimbing Monotonicity:**
   ```bash
   python3 tools/radar/cli.py status /home/oguz/MS-Randevu-monolith
   ```
   Ensure the targeted finding in `.edge/ledger/core.json` is resolved and `health_score` is improved ($\text{Score}_{t+1} \ge \text{Score}_t$).

3. **Commit & Submit:**
   Create a clean, atomic micro-commit following Conventional Commits:
   ```bash
   git add src/actions/<domain>.ts src/lib/<domain>/repository.ts src/core/ tests/
   git commit -m "refactor(core): extract <operation> from <domain> action to repository and pure core"
   ```
   Report the commit hash and ledger delta back to the coordinator agent.
