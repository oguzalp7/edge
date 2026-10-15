# 📋 Domain Refactoring Watchlist & Cycle Log

**Kayıt ID:** `CYCLE-CORE-CUSTOMERS-001`  
**Domain / Kapsam:** `customers` (`src/actions/customers.ts` ➔ `src/lib/customers/repository.ts`)  
**Tarih:** 2026-10-05  
**Saat:** 00:03:06 EDT  
**Hedef Dal:** `refactor/core-customers` ➔ `feat/nextjs-clean-monolith`  
**GitHub PR:** [PR #33](https://github.com/oguzalp7/MS-Appointment/pull/33)  
**Nihai Commit:** `4b9989d0a777c64791b69dd1bfc387b18da04922`  

---

## 🔄 Yaşam Döngüsü Özeti (Pipeline Trajectory)

| Aşama | İşlem / İstasyon | Araç / Yöntem | Sonuç |
| :--- | :--- | :--- | :--- |
| **1. Gözlem** | Churn & Borç Tespiti | `tools/radar/` (`churn.py`) | 5 Fat Function, 1 Arrow Anti-Pattern, 1 SQL Leak tespit edildi. |
| **2. Kapı** | Güvenlik Kaideleri | `tools/gate.py` | MigrationGate, Target SLOC < 0, Scaffolding Allowance (+25) devrede. |
| **3. Tırmanış** | Poteto Hillclimbing | Mikro-Commitler (#1..#5) | `deleteCustomer`, `updatePhone`, `updateCustomer`, `toggleStatus`, `lookup`, `findOrCreate`, `history` |
| **4. Denetim** | Çift Eksenli Review | `/code-review` (2 Alt-Ajan) | Standart (tip hilesi) ve Spec (`db.transaction` eksikliği) bağımsız yakalandı. |
| **5. Cila** | Polish & Hardening | Commit `81f636f` | Drizzle `Customer` SSOT bağlandı, multi-table yazımları `db.transaction()` ile sarıldı. |
| **6. Staging** | no-mistakes Boru Hattı | `no-mistakes axi run --skip ci --yes` | Rebase, Review auto-fix, Test, Document, Lint, Push tamamlandı, PR #33 açıldı. |

---

## ✅ İNCELENDİ CHECKLIST (Verifikasyon Matrisi)

- [x] **MigrationGate Invariant:** `src/db/schema/*` ve `drizzle/` dizinlerine kesinlikle dokunulmadı (0 şema değişikliği).
- [x] **Hedef Kapsam Daralması:** `src/actions/customers.ts` dosyası 880 satırdan 432 satıra indirildi (Net: **-448 satır**).
- [x] **Scaffolding Bütçesi:** `src/lib/customers/repository.ts` (+268 satır) kuruldu.
- [x] **Global SLOC Kazancı:** Üretim kod tabanı net **-180 satır** daraltıldı (Slop / kod şişirme engellendi).
- [x] **Veritabanı Sızıntıları:** Server Action katmanındaki tüm ham `db.select`, `db.insert`, `db.update`, `db.delete` sızıntıları temizlendi.
- [x] **Tip Güvenliği (Zero Type Tampering):** `CustomerRecord` içindeki `[key: string]: any;` index signature çöpe atıldı, Drizzle şema tipleri korundu.
- [x] **ACID & Atomiklik:** `findOrCreateCustomer` ve `updateCustomerAndProfile` ardışık yazımları `db.transaction()` ile atomik hale getirildi.
- [x] **Hızlı Karakterizasyon Seam:** `tests/unit/customers/customers.test.ts` (10/10 birim test, 1.35s) her mikro adımda yeşil kaldı.
- [x] **Monolit Entegrasyon Testi:** 94 test dosyası, 922 birim test tam pakette yeşil geçti.
- [x] **Bilingual Docs & Navigation:** no-mistakes pipeline dokümantasyon ve linter güncellemelerini mühürledi.
- [x] **Dal Senkronizasyonu:** `feat/nextjs-clean-monolith` dalı uzak baş (`4b9989d`) ile eşitlendi.

---

## 📌 Sonraki Domain Sırası (Backlog Queue)

1. `src/actions/bookings.ts` (Raw SQL sızıntıları & Booking Transaction refaktörü)
2. `src/actions/pricing.ts` (Kampanya kuralları ve snapshot hesaplama motoru)
3. `src/actions/branches.ts` & `locations.ts` (M2M ilişkileri ve seed/setup ayrımı)
