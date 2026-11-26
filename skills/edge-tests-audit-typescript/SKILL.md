---
name: edge-tests-audit-typescript
profile: typescript
description: Deterministic TypeScript test purity, external I/O leakage, and test isolation health auditor. Detects live database imports, direct DML/DDL executions, uncontained seeds, missing teardowns, and static data collisions in unit tests.
---

# 🧪 /edge-tests-audit-typescript — TypeScript Test Purity & Isolation Health Auditor

> **Stack Profile:** `typescript` (extends cleanly to `nextjs-drizzle-tailwind`) — see [`profiles/typescript/PLAYBOOK.md`](../../profiles/typescript/PLAYBOOK.md).

Bu beceri, `tests/unit/` dizini altındaki TypeScript birim testlerinin dış dünya (veritabanı, DDL/DML, seed betikleri, ağ) bağımlılıklarını deterministik olarak analiz eder ve testlerin hermetiklik (saflık) puanını hesaplar.

---

## ⚡ Kullanım

Hedef bir test dizinini veya dosyasını denetlemek için:

```bash
# Renkli konsol tablosu (İnsan formatı — macOS/Linux/WSL)
python3 ~/.gemini/config/plugins/edge/tools/test_audit/cli.py <target-path>

# Windows PowerShell:
python "$env:USERPROFILE\.gemini\config\plugins\edge\tools\test_audit\cli.py" tests/unit

# AXI / Ajan formatı (Token-Oriented Object Notation)
python3 ~/.gemini/config/plugins/edge/tools/test_audit/cli.py tests/unit --format toon

# Sıkı Kapı Doğrulaması (Herhangi bir toksik test varsa fail et)
python3 ~/.gemini/config/plugins/edge/tools/test_audit/cli.py tests/unit --strict-pure

# Raporu markdown dosyasına kaydetme
python3 ~/.gemini/config/plugins/edge/tools/test_audit/cli.py tests/unit -o test_health_report.md
```

---

## 📊 Değerlendirme ve Puanlama Rubriği (Purity Scoring)

Her test dosyası **100 puan** ile başlar. Aşağıdaki ihlaller puanı düşürür veya artırır:

| İhlal / Kural | Ceza / Bonus | Açıklama |
| :--- | :---: | :--- |
| **`DB_CLIENT_IMPORT`** | **-35p** | Doğrudan `@/db` veya `@/db/index` istemcisinin ithal edilmesi. |
| **`DB_DML_EXECUTION`** | **-25p** | `db.insert`, `db.update`, `db.delete`, `db.transaction` çağrıları. |
| **`NO_TEARDOWN`** | **-25p** | Veritabanı yazımı olmasına rağmen `afterAll`/`cleanup` bulunmaması (DB Zehirleme). |
| **`DDL_OR_SEED_EXECUTION`** | **-20p** | `seedCanonical*()` veya `ensure*Tables()` gibi DDL/seed fonksiyonlarının çağrılması. |
| **`SERVER_ACTION_IMPORT`** | **-15p** | `@/actions/*` katmanına doğrudan bağımlılık (Controller bypass). |
| **`WEAK_TEARDOWN`** | **-10p** | `afterAll` mevcut ancak somut temizlik/delete işlemi yetersiz. |
| **`HARDCODED_DATA_COLLISION`** | **-5p** | DB yazımında statik telefon numarası (ör. `5551234567`) kullanımı (Çakışma riski). |
| **`ISOLATED_MOCKING`** | **+10p** | `vi.mock`, `vi.fn`, `vi.spyOn` ile bellek içi izole test tasarımı. |
| **`PURE_CORE_ENGINE`** | **+15p** | Saf Domain/Core motor testi (Hermetik kural). |

### Puan Kategorileri:
- **`[85 - 100]` 🟢 PURE UNIT:** Saf hermetik birim test (RAM üzerinde çalışır, <100ms).
- **`[50 - 84]` 🟡 MASKED INTEGRATION:** Birim test kılığına girmiş kısmi entegrasyon testi.
- **`[00 - 49]` 🔴 TOXIC (LEAKY):** Canlı veritabanını kirleten zehirli test; acil taşınmalı veya mocklanmalıdır.

---

## 🛠️ İyileştirme Protokolü (Remediation Playbook)

1. **Entegrasyon Testine Taşı:**  
   Veritabanı bağlantısı zorunlu olan ve gerçek SQL davranışını test eden dosyaları `tests/integration/<domain>/` dizinine taşıyın.
2. **Repository Mocking:**  
   Controller / Server Action (`nextjs-drizzle-tailwind` profili) veya orkestratör testlerinde `vi.mock("@/lib/<domain>/repository")` kullanarak DB katmanını sanallaştırın.
3. **In-Memory Driver:**  
   Domain repository'sinin `In-Memory Driver` desteğini kullanarak bellekte sıfır I/O ile testleri koşturun.
