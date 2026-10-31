---
name: edge-gnhf
description: Autonomous Overnight Worktree Engine ("Good Night, Have Fun"). Bridges in-chat conversational handshake, dual-signal physical hook armor, ephemeral model quota shield, porcelain worktree tracking, and gate-verified morning harvest.
suggested_skills:
  - edge-orchestrator
  - edge-audit
  - edge-radar
---

# 🌙 /edge-gnhf — Otonom Gece Boyu Worktree Motoru ("Good Night, Have Fun")

> *"Geceleri dinlenirken kod tabanınız güvenle iyileşsin. İzole Git worktree garantisi, çift-sinyalli hook kalkanı, harcanabilir model kota koruyucusu ve kapı-onaylı sabah hasadı."*

`edge-gnhf`, geliştiricilerin uzun süren mekanik refaktör, lint temizliği veya atomik hata giderme işlerini gece boyu otonom bir ajana devretmesini sağlayan deterministik bir yaşam döngüsü motorudur.

---

## 🧭 İki Temel İlke ve Kesin İnvaryantlar

1. **Sohbet İçi GNHF Çalıştırma Yasağı (Pure Handshake Mandate):**
   > [!CRITICAL]
   > Sohbet ajanı (Orkestratör) **ASLA `edge-gnhf run` veya `gnhf` komutunu `run_command` üzerinden doğrudan tetiklemez!**  
   > Otonom döngü saatler sürebilir; sohbet penceresinde çalıştırılması bağlam patlamasına, token israfına ve zaman aşımı kesintilerine yol açar. Ajan yalnızca **kapsam analizi yapar, komutu hazırlar ve sabah hasadını yönetir.**

2. **Kota Kalkanı (Quota Shield - Zero Flagship Burn):**
   - Gece döngüsü varsayılan olarak **`gemini-3.8-flash-medium`** modelini kullanır.
   - Amiral gemisi modellerin (`gemini-4-argon-*`, `gemini-2.5-pro`) pahalı kotaları harcanmaz.
   - Kullanıcının global konfigürasyon dosyaları (`~/.gnhf/config.yml`) asla kirletilmez; geçici `/tmp` PATH sarmalayıcısı ile izole edilir.

3. **İzole Git Worktree Garantisi:**
   - Otonom koşular doğrudan ana çalışma ağacına dokunmaz; izole `gnhf/*` worktree dallarında koşar.
   - Ana geliştirme dalı (`development` / `main`), sabah `tools/gate.py` kalite kapısı %100 yeşil olmadan birleştirilemez.

4. **Çift Sinyalli Hook Zırhı (`EDGE_AFK`):**
   - Alt ajan çağrısı (`invoke_subagent`) kesin olarak engellenir (Single-Agent Invariant).
   - Orkestrasyon durum dosyaları (`.edge/brigade.json`, `edge_active_stations.json`) kilitlenir.

---

## 💻 1. İnsan Dostu Terminal Rehberi (Human Terminal Guide)

Kullanıcı, terminalinde `edge-gnhf` komutunu doğrudan çalıştırabilir:

### A. Otonom Koşu Başlatma (`run`)
```bash
# Standart güvenli refaktör (strict mod - testler ve şemalar korunur)
edge-gnhf run /home/oguz/next-enterprise "Decouple legacy Stripe webhook handlers into repository pattern"

# Test ve şema mutasyonuna izin veren koşu (yolo mod)
edge-gnhf run /home/oguz/next-enterprise "Overhaul auth models and update integration tests" --yolo

# Önizleme (dry-run - prompt ve çözümlenen komutu ekrana basar, alt-işlem başlatmaz)
edge-gnhf run /home/oguz/next-enterprise "Decouple stripe webhook" --dry-run

# Özel kısıtlamalar ve komutlar ile
edge-gnhf run /home/oguz/next-enterprise "Migrate server actions" \
  --mode strict \
  --track core \
  --max-iterations 20 \
  --max-tokens 300000 \
  --test-cmd "npx vitest run src/billing.test.ts"
```

#### Mod Karşılaştırması:
| Kural / Dizin | `strict` Mod (Varsayılan) | `yolo` Mod (`--yolo`) |
|---|---|---|
| `src/**`, `app/**`, `lib/**` | ✅ Serbest | ✅ Serbest |
| `tests/**`, `*.test.*`, `*.spec.*` | ❌ **YASAK** (Test İmmutability) | ✅ İzin Verilir |
| `db/schema/**`, `drizzle/**` | ❌ **YASAK** (MigrationGate) | ✅ İzin Verilir |
| `invoke_subagent` (Alt ajan) | ❌ **YASAK** | ❌ **YASAK** |
| `.edge/*.json` (HITL durum dosyaları) | ❌ **YASAK** | ❌ **YASAK** |

---

### B. Durum ve Blocker Takibi (`status`)
Sabah terminale dönüldüğünde aktif veya tamamlanan worktree'lerin durumunu ve triaj notlarını görüntüler:
```bash
edge-gnhf status /home/oguz/next-enterprise
```

**Örnek Çıktı:**
```text
🌙 Edge-GNHF Active Worktrees Status: /home/oguz/next-enterprise
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Worktree: /home/oguz/next-enterprise/.worktrees/gnhf-refactor-api
Branch:   gnhf/refactor-api-routes
Base:     development
Commits:  14 commits ahead of development
Last Run: 2026-10-31 03:45:12 UTC ("refactor: decouple customer billing actions")

⚠️ Triaged Blockers ([SKIPPED-NEEDS-HITL]):
  1. src/server/auth.ts: Circular dependency with user-session repository.
  2. src/db/schema/org.ts: Schema locked in strict mode; requires migration.

Status: READY FOR HARVEST (`edge-gnhf harvest /home/oguz/next-enterprise gnhf/refactor-api-routes`)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

### C. Sabah Hasadı ve Birleştirme (`harvest`)
Kalite kapısını (`gate.py`) doğrular, diff özetini çıkarır ve temiz fast-forward birleştirme yapar:
```bash
# Önizleme (dry-run) - hiçbir şeyi değiştirmez
edge-gnhf harvest /home/oguz/next-enterprise gnhf/refactor-api-routes --dry-run

# Doğrula, development dalına fast-forward merge et ve worktree'yi temizle
edge-gnhf harvest /home/oguz/next-enterprise gnhf/refactor-api-routes --base development --merge --cleanup
```

---

## 🤝 2. Ajan Dostu Sohbet El Sıkışma Protokolü (Pure Handshake Protocol)

Sohbet ajanı `/edge-gnhf` komutunu aldığında aşağıdaki iki fazlı el sıkışma protokolünü izler:

### 🌙 Faz 1: Akşam Hazırlığı (Evening Preparation)
1. **Hedef Kapsam Belirleme:**
   - Eğer kullanıcı belirli bir hedef belirtmediyse:
     - Salt-okunur olarak `python3 /mnt/c/Users/oguz_/.gemini/config/plugins/edge/tools/audit/cli.py` veya `python3 /mnt/c/Users/oguz_/.gemini/config/plugins/edge/tools/radar/scanner.py` çalıştırır.
     - En çok teknik borç barındıran (God files, yüksek cyclomatic complexity, CRAP skoru yüksek) Top-3 hedefi kullanıcıya sunar.
2. **Güvenlik Modu Hizalaması:**
   - Kod kalitesi ve mimari refaktör için `--mode strict` önerir.
   - Şema değişikliği veya test yazımı gerekiyorsa insan onaylı `--mode yolo` mutabakatı sağlar.
3. **Komut Üretimi ve Teslimi:**
   - Kullanıcının doğrudan WSL2 terminaline yapıştıracağı tam komutu kod bloğu olarak sunar:
     ```bash
     edge-gnhf run /home/oguz/<project> "<synthesized-objective>" --mode strict --track all
     ```
4. **Kullanıcıya Yönlendirme:**
   - Kullanıcıya terminali açık bırakarak uyumasını tavsiye eder. İhtiyaç halinde `/schedule` komutunu hatırlatır.

---

### ☀️ Faz 2: Sabah Hasadı (Morning Reconnaissance)
Kullanıcı sabah sohbete dönüp `/edge-gnhf status` veya `/edge-gnhf harvest` dediğinde:
1. **Durum Taraması:**
   - Ajan `edge-gnhf status /home/oguz/<project>` komutunu `run_command` ile çalıştırır.
   - Gece atılan commit sayısını, son commit mesajını ve triaj edilen `[SKIPPED-NEEDS-HITL]` engellerini kullanıcıya raporlar.
2. **Kalite Kapısı & Diff Özeti:**
   - `edge-gnhf harvest /home/oguz/<project> --dry-run` çalıştırarak kalite kapısının durumunu ve diff istatistiklerini kontrol eder.
3. **İsteğe Bağlı EXAMINER İncelemesi:**
   - Kullanıcı detaylı mimari inceleme isterse:
     - `EXAMINER` istasyon çalışanını (`Model: "flash"`) göreve çağırarak diff üzerinde standart denetimi yaptırır.
4. **İnsan Onayı ile Birleştirme:**
   - Ajan asla onay almadan merge yapmaz.
   - İnsan onayının ardından `edge-gnhf harvest /home/oguz/<project> --merge --cleanup` komutunu çalıştırır ve nihai entegrasyonu raporlar.
