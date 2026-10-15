# 📖 Operational Playbook: Bookings Domain Architecture & Refactoring Recipes

> [!NOTE]
> Bu operasyonel el kitapçığı, `edge-distill` motoru tarafından **Bookings** domaini üzerindeki gerçek cerrahi adımlardan, derleyici loglarından, FSM durum geçişlerinden ve git mikro-commit'lerinden otomatik olarak damıtılmıştır (distilled).

---

## 🧭 1. Domain Profili ve Veri İzi Bağlamı (Data Trail Context)

| Metrik / Parametre | Değer |
| :--- | :--- |
| **Hedef Domain** | `bookings` |
| **İz / Hat (Track)** | `CORE` |
| **Hedef Kontrolör** | `src/actions/bookings.ts` |
| **Modüler Depo (Repository)** | `src/lib/bookings/repository.ts` |
| **Temel Dal (Base Branch)** | `feat/nextjs-clean-monolith` |
| **Aktif Dal (Active Branch)** | `N/A` |
| **Kaynak Bilet ID** | `N/A` |
| **Damıtılma Zamanı** | `2026-10-06T00:56:41.364960+00:00` |

---

## 🚫 2. Negatif Kısıtlar Kütüğü (Negative Constraints Ledger)

> [!CAUTION]
> **Sıfır Toleranslı Mimari İhlaller:**
> Aşağıdaki anti-pattern'ler doğrudan `tools/gate.py` veya derleyici tarafından engellenir. Bu kural ve kısıtları ihlal eden cerrahi adımlar derhal geri alınır (rollback).

### 🔴 [KRİTİK] Zero Schema / Migration File Mutations
* **Anti-Pattern:** Modifying src/db/schema/* or drizzle/* files during refactoring tasks.
* **Risk / Neden Yasak:** Causes production migration divergence and breaks Stage 1 MigrationGate invariant.
* **Zorunlu Reçete (Required Pattern):** Keep schema files 100% untouched. Handle transformations in repository.
* **Kural Kodu:** `RULE-MIGRATION-GATE` (Kaynak: `invariant`)

### 🔴 [KRİTİK] No Direct DB Operations in Server Actions
* **Anti-Pattern:** Calling db.select(), db.insert(), db.update(), or db.delete() directly inside src/actions/.
* **Risk / Neden Yasak:** Leaks database implementation details into presentation/action controllers, preventing mocking and reuse.
* **Zorunlu Reçete (Required Pattern):** Delegate all queries and mutations to src/lib/<domain>/repository.ts.
* **Kural Kodu:** `RULE-CORE-DB-LEAK` (Kaynak: `invariant`)

### 🔴 [KRİTİK] No Unprotected Multi-Table Writes
* **Anti-Pattern:** Writing to multiple database tables in sequence without wrapping in db.transaction().
* **Risk / Neden Yasak:** Creates race conditions, orphaned records, and partial database corruption on failure.
* **Zorunlu Reçete (Required Pattern):** Wrap multi-step writes in await db.transaction(async (tx) => { ... }).
* **Kural Kodu:** `RULE-ACID-TRANSACTIONS` (Kaynak: `invariant`)

### 🔴 [KRİTİK] No Index Signature Tampering or Loose Any
* **Anti-Pattern:** Adding [key: string]: any; to records or casting with 'as any' to bypass compiler errors.
* **Risk / Neden Yasak:** Defeats TypeScript compiler verification and introduces runtime undefined errors.
* **Zorunlu Reçete (Required Pattern):** Use explicit Drizzle InferSelectModel and InferInsertModel types.
* **Kural Kodu:** `RULE-TYPE-SAFETY` (Kaynak: `invariant`)

---

## 🔄 3. Yapısal Dönüşüm Şablonu (AST & Code Diff Pattern)

> [!IMPORTANT]
> **Daralma İlkesi (Contraction Invariant):** `src/actions/bookings.ts` dosyası kesinlikle daralmalıdır ($\Delta\text{SLOC} < 0$). Veritabanı sorguları ve mutasyonları tamamen domain repository katmanına izole edilmelidir.

**Açıklama:** Extracted monolithic database queries from src/actions/bookings.ts into src/lib/bookings/repository.ts.

### ❌ ÖNCE (BEFORE): Monolitik Kontrolör & SQL Sızıntısı
```typescript
// ❌ BEFORE: Monolithic Fat Controller (bookings.ts)
// Direct DB operations, un-isolated transaction, loose types
export async function createBooking(formData: FormData) {
  const session = await auth();
  if (!session?.user) throw new Error("Unauthorized");

  const name = formData.get("name") as string;
  const email = formData.get("email") as string;

  // Anti-Pattern: Direct Drizzle leak in Server Action
  const existing = await db
    .select()
    .from(bookingsTable)
    .where(eq(bookingsTable.email, email));

  if (existing.length > 0) throw new Error("Booking exists");

  // Anti-Pattern: Multi-table write without db.transaction()
  const [booking] = await db
    .insert(bookingsTable)
    .values({ name, email })
    .returning();

  await db.insert(auditLogsTable).values({
    action: "CREATE_BOOKINGS",
    entityId: booking.id,
    userId: session.user.id,
  });

  revalidatePath("/bookings");
  return booking;
}
```

### ✅ SONRA (AFTER): İnce Kontrolör & Atomik Domain Repository
```typescript
// ✅ AFTER: Thin Controller + Domain Repository (src/lib/bookings/repository.ts)
// Layered architecture: Auth/Validation in action, persistence in repository

// 1. Controller: src/actions/bookings.ts (Thin orchestrator)
export async function createBooking(formData: FormData) {
  const session = await requireAuth();
  const input = parseBookingInput(formData);

  // Persistence delegated to repository with atomic ACID transaction
  const result = await bookingRepository.createWithAudit(input, session.user.id);
  
  revalidatePath("/bookings");
  return result;
}

// 2. Repository: src/lib/bookings/repository.ts (Isolated DB operations)
export const bookingRepository = {
  async createWithAudit(input: CreateBookingInput, userId: string) {
    return await db.transaction(async (tx) => {
      const [booking] = await tx
        .insert(bookingsTable)
        .values(input)
        .returning();

      await tx.insert(auditLogsTable).values({
        action: "CREATE_BOOKINGS",
        entityId: booking.id,
        userId,
      });

      return booking;
    });
  },
};
```

---

## 🛟 4. Kurtarma Döngüleri ve İyileştirme Reçeteleri (Rescue Loops)

> [!TIP]
> **Kanıtlanmış Deterministik Çözümler:**
> Ajanlar kapılarda takıldığında veya derleyici hataları aldığında rastgele deneme-yanılma yapmak yerine aşağıdaki deterministik reçeteleri uygular.

### 🛠️ [SURGERY] MigrationGate Invariant: Refactoring must never touch schema or migration files.
* **Hata Semptomu (Symptom):** Accidental modification of database schemas (src/db/schema/*) during refactoring.
* **Kök Neden (Root Cause):** Attempting to resolve domain discrepancies by altering DB schema rather than mapping in the repository layer.
* **Deterministik Müdahale (Rescue Move):** Revert schema changes (`git checkout -- src/db/schema/`). Perform column aliasing and type casting inside `src/lib/<domain>/repository.ts`.
* **Doğrulama Komutu (Verification Command):**
  ```bash
  git diff --name-only feat/nextjs-clean-monolith...HEAD
  ```

### 🛠️ [REVIEW] ACID Purity Rule: All multi-entity modifications must be executed within atomic transactions.
* **Hata Semptomu (Symptom):** Dual-axis review flags un-isolated multi-table writes as CRITICAL ACID violation.
* **Kök Neden (Root Cause):** Executing multiple sequential database writes without atomic transaction boundaries.
* **Deterministik Müdahale (Rescue Move):** Wrap sequential writes inside `await db.transaction(async (tx) => { ... })` and pass the `tx` client to repository methods.
* **Doğrulama Komutu (Verification Command):**
  ```bash
  npm run test:unit -- tests/unit/bookings/bookings.test.ts
  ```

### 🛠️ [VERIFY] Zero Type Tampering: Do not loosen type definitions with 'any' or index signatures.
* **Hata Semptomu (Symptom):** TypeScript error: Type 'any' or index signature mismatch on database record.
* **Kök Neden (Root Cause):** Use of permissive index signature `[key: string]: any` to silence compiler instead of strict Drizzle types.
* **Deterministik Müdahale (Rescue Move):** Import $InferSelectModel<$table> directly from schema and declare explicit domain entity types.
* **Doğrulama Komutu (Verification Command):**
  ```bash
  npx tsc --noEmit
  ```

---

## 🧪 5. Hermetik Doğrulama ve Test Seam Reçetesi

Bu domain için belirlenmiş birim test dikişi: `npm run test:unit`

---

## ✅ 6. Operasyonel Kontrol Listesi (Deterministic Verification Matrix)

- [ ] **MigrationGate Invariant:** `src/db/schema/*` ve `drizzle/` dizinlerine kesinlikle dokunulmadı (0 şema değişikliği).
- [ ] **Hedef Kapsam Daralması:** `src/actions/bookings.ts` dosyası kesinlikle daraldı ($\Delta\text{SLOC} < 0$).
- [ ] **Scaffolding Bütçesi:** Eklenen repository satırları tanımlı toleransı aşmadı.
- [ ] **Veritabanı İzolasyonu:** Kontrolörde ham `db.select`, `db.insert`, `db.update`, `db.delete` çağrısı kalmadı.
- [ ] **ACID & Atomiklik:** Çoklu tablo mutasyonları `db.transaction()` bloğu içinde güvene alındı.
- [ ] **Tip Bütünlüğü:** `[key: string]: any;` veya `as any` tip kaçamağı içermez; Drizzle şema tipleri korundu.
- [ ] **Karakterizasyon Testleri:** `npm run test:unit` testi 100% yeşil geçti.
- [ ] **TypeScript Temizliği:** `npx tsc --noEmit` hatasız (0 error) sonuç verdi.
- [ ] **Verification Gate:** `python tools/gate.py` sıfır hatayla geçti.

### 💻 Deterministik Doğrulama Komutları (Terminal One-Liners)

```bash
# 1. Şema ve dosya izolasyonunu doğrula (MigrationGate)
git diff --name-only feat/nextjs-clean-monolith...HEAD

# 2. SLOC daralmasını ve bütçeyi doğrula (Target Contraction)
git diff --numstat feat/nextjs-clean-monolith...HEAD

# 3. TypeScript tip kontrolünü çalıştır
npx tsc --noEmit

# 4. Karakterizasyon test seam'ini çalıştır
npm run test:unit

# 5. Tam Edge Verification Gate'i çalıştır
python tools/gate.py . --base feat/nextjs-clean-monolith --track core --target-file src/actions/bookings.ts
```
