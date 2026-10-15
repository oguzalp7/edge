---
name: edge-distill
description: Incident Flight Recorder, Operational Journaler & Domain Playbook Miner. Records live crisis interventions (divergent features, missing seams, behavioral bugs), maintains durable journals from incident start to resolution, and distills evidence-based domain playbook proposals.
---

# ✈️ /edge-distill — Incident Flight Recorder & Operational Playbook Miner

> *"Do not force generic coding standards onto crisis scenarios. When faced with architectural disasters — bifurcated features, behavioral divergence, missing seams, and bugs — engage the Flight Recorder. Journal every diagnosis, seam addition, and synchronization move until 'problem resolved' sign-off, then distill an empirical Playbook Proposal."*

`edge-distill` is a dual-purpose engine:
1. **Kara Kutu (Flight Recorder & Operational Journal):** Kriz anında başlatılan, problem çözüldü onayına kadar kesintisiz adımları, kararları ve diff'leri kaydeden canlı operasyon günlüğü.
2. **Domain Keşif & Playbook Miner:** Çözüm sonrası oturumu tarayarak yeni operasyonel domainler (örneğin `reconcile` / `harmonize`) ve kanıta dayalı el kitapçığı taslakları (`rules/playbooks/proposals/`) üreten analiz motoru.

---

## 🏛️ Edge Eklentisinde "Domain" Ne Demektir?

> [!IMPORTANT]
> **Proje Kodu Alanları vs Operasyonel Ajan Domainleri:**
> `edge` altyapısında "domain", hedef uygulamanın bir modülü (bookings, customers vb.) DEĞİL; **ajanın çalışma modu ve mühendislik arketipidir.**

Şu ana kadar tanımlı 2 ana operasyonel domain vardı:

| Domain | Temel Felsefe | Davranış (Behavior) | Yapı (Structure) | Kısıtlar |
| :--- | :--- | :--- | :--- | :--- |
| **`feature`** | Dıştan İçe (Outside-In) | **DEĞİŞİR** (Yeni yetenek) | Yeni eklenir | `Target SLOC < 0` aranmaz, kabul kriteri esastır (`rules/feature.md`). |
| **`refactor`** | İçten Dışa (Inside-Out) | **SABİTTİR** (0 değişim) | Sadeleşir / Katmanlanır | `Target SLOC < 0` zorunludur, testler baştan yeşil olmalıdır (`rules/refactor.md`). |

### 🚨 Yeni Keşfedilen 3. Domain: `reconcile` (Harmonization / Stabilization)
Ajanların ve mühendislerin karşılaştığı tipik felaket senaryosu:
* **Durum:** Aşırı şişkin LOC, eksik test dikişleri (seam'ler), DB ve API farklı kafada, Core ayrı kafada, iki farklı davranış sergileyen iki başlı bir feature ve çözülmeyi bekleyen bir bug.
* **Neden `refactor` uygulanamaz?** Davranış dondurulamaz; çünkü bug vardır ve iki baş birbiriyle çelişmektedir. Üstelik baştan yeşil bir test dikişi yoktur.
* **Neden `feature` uygulanamaz?** Feature zaten mevcuttur; sıfırdan yazmak sisteme 3. bir baş ekler.
* **Çözüm:** **`reconcile` Protokolü:**
  1. *İki Başın Tespiti:* API/Action beklentileri ile Core/DB gerçekliği arasındaki sapmayı haritala.
  2. *Eksik Dikiş İnşası:* Önce beklenen davranışı mühürleyen karakterizasyon testlerini yaz.
  3. *Davranış Senkronizasyonu & Bug Fix:* İki davranışı tek bir SSOT sözleşmesine indirge ve bug'ı çöz.
  4. *Artık Başın Ayıklanması:* Çelişkili ikinci implementasyonu temizle, LOC şişkinliğini daralt.

---

## 🔄 Kara Kutu Yaşam Döngüsü (Flight Recorder Lifecycle)

```
 [ Kriz Başlangıcı ]
         │
         ▼
 1. BAŞLAT: `brigade distill start . --goal "İki başlı auth/order senkronizasyonu"`
         │   (Baseline commit SHA, git status ve zaman damgası kilitlenir)
         │
         ▼
 2. KAYDET: `brigade distill log . --step "Eksik seam characterization testi yazıldı" --tag SEAM_CREATION`
         │   `brigade distill log . --step "API ve Core arasındaki parametre farkı giderildi" --tag BEHAVIOR_SYNC`
         │   `brigade distill log . --step "Deadlock bug'ı db.transaction ile çözüldü" --tag BUG_FIX`
         │
         ▼
 3. PROBLEM ÇÖZÜLDÜ ONAYI: `brigade distill resolve . --notes "Seamler yeşil, davranış tekilleştirildi"`
         │   (Final commit SHA mühürlenir, kayıt durdurulur)
         │
         ▼
 4. TASLAK ÜRETİMİ: `brigade distill propose .`
         │
         ▼
 [ rules/playbooks/proposals/reconcile-domain-proposal.md Hazırlanır ]
```

---

## ⚡ CLI Referansı

### 1. Canlı Kara Kutu Komutları
```bash
# Oturumu Başlat
python tools/brigade/cli.py distill . --action start --goal "İki başlı feature senkronizasyonu" --domain reconcile

# Günlüğe Adım Ekle
python tools/brigade/cli.py distill . --action log --step "tests/unit/ içinde karakterizasyon dikişi atıldı" --tag SEAM_CREATION
python tools/brigade/cli.py distill . --action log --step "Controller ve Core tek SSOT metoduna bağlandı" --tag BEHAVIOR_SYNC

# Durumu İncele
python tools/brigade/cli.py distill . --action status

# Problem Çözüldü Olarak Mühürle
python tools/brigade/cli.py distill . --action resolve --notes "Bug çözüldü, seamler yeşil, ikinci baş ayıklandı"

# Yeni Playbook Proposal'ı Üret
python tools/brigade/cli.py distill . --action propose
```

### 2. Standalone CLI Komutları
```bash
# Bağımsız CLI ile aynı işlemler:
edge-distill start . --goal "Divergent API/DB reconciliation"
edge-distill log . --step "Characterization seam erected" --tag SEAM_CREATION
edge-distill resolve . --notes "Single source of truth established"
edge-distill propose .
```

---

## 📄 Üretilen Playbook Proposal İçeriği

`rules/playbooks/proposals/<domain>-domain-proposal.md` belgesi şunları içerir:
1. **Kriz Arketipi & İki Başlı Yapı Analizi:** Head A (API) vs Head B (Core) uyuşmazlığı.
2. **Kronolojik Kara Kutu Günlüğü:** Kriz anından onay anına kadar atılan tüm adımlar.
3. **Eksik Dikiş İnşası ve Senkronizasyon Reçetesi:** Test seam'leri ve kurtarma hamleleri.
4. **Yapısal Dönüşüm (Before / After):** İki başlı durumdan tek başlı SSOT'a geçiş.
5. **Önerilen Yeni Domain Anayasası:** Bu arketipteki sonraki krizler için kalıcı kurallar.
6. **Çıkış Kriterleri ve Doğrulama Matrisi.**
