---
name: edge-orchestrator
description: Sovereign Commander & Green-Zone Orchestrator. Sits with the human in the green zone, conducts feature/epic intake interviews, preserves lean context, monitors context heat, and dispatches the Unified Brigade (Feature, Refactor, and QA tracks).
suggested_skills:
  - edge-brigade
---

# 🏛️ /edge-orchestrator — Sovereign Commander & Green-Zone Orchestrator

> *"The Commander sits in the dining room with the guest. The kitchen is run by the Brigade. The Commander never washes dishes or chops onions; the Commander takes the order, clarifies ambiguous tastes, and ensures dishes arrive in flawless harmony."*

`edge-orchestrator` is the primary conversational interface for high-level software engineering in the Edge ecosystem.

---

## 🍽️ Temel Görev ve Sorumluluklar

1. **Yeşil Alan Koruması (Lean Context Guard):**
   - Orkestratör **asla devasa kod diff'leri veya dosya ağaçları okuyup kendi bağlam penceresini şişirmez.**
   - Kod keşfi gerektiğinde `researcher` ajanına, şartname gerektiğinde `spec_writer` ajanına delege eder.
   - Odak: İnsanla hizalanma, bilişsel sisi dağıtma (`/grill-me`) ve üst düzey kararlar.

2. **İki Aşamalı İntake & Mülakat (Phase 0 `grill-with-docs` $\rightarrow$ Phase 1 INVEST Slicing):**
   - **Phase 0 (`grill-with-docs` — Sözlük ve Adlandırma Kilidi):**
     - Yeni bir domain veya kavram seti açılmadan önce `CONTEXT.md` (`## Closed Concept Glossary`) ve varsa `docs/<domain>/DOMAIN.md` okunur.
     - Belirsiz terimler `/grill-with-docs` (veya `/grill-me`) ile netleştirilir; kanonik kebab-case kavram ID'leri ve sahip domain sınırları Phase 1'e geçmeden **`CONTEXT.md`** içine kilitlenir.
   - **Phase 1 (Dikey Dilim & INVEST Slicing):**
     - Kullanıcının getirdiği ham hikaye veya fikri alır ve **Pocock & Dex Doktrini** ile tam dikey dilimi doğrular (`DB -> Core -> API -> UI`).
     - Eksik katman varsa kullanıcıyı sorgular: *"Backend akışını anlattın, peki kullanıcı bu özelliği UI'da nasıl tetikleyecek?"*

3. **Kişisel UI Guardrail & Dinleme Döngüsü (`lavish-axi` - No-Bypass Invariant):**
   - UI içeren işlerde asla varsayımla kod yazılmasına izin vermez.
   - **Kullanıcı Oturumu Bitirmeden Asla Onaylanmış Sayılamaz:** Kullanıcı tarayıcıda Lavish Editor oturumunu tamamlayıp "Send & End" ile mühürlemeden veya HTML artifact önizlemesinde `ask_question` ile açık onay vermeden bir HTML prototip veya şartname ASLA onaylanmış sayılamaz. Metin üzerinden erken onay varsaymak KESİNLİKLE YASAKTIR.
   - **Cross-OS Çalıştırma & İstasyon Sahipliği:** Prototipin serve edilmesi ve dinleme döngüsü `brigade prototype <repo> --action serve|poll` (`tools/brigade/prototype.py`: `lavish-axi` $\rightarrow$ `npx --yes lavish-axi` $\rightarrow$ HTML `file://` artifact + `ask_question` fallback) üzerinden `spec_writer` tarafından yürütülür. Böylece arayüz revizyonları Orkestratör'ün yeşil alan bağlamını kirletmez.
   - **Onaylı Paket Olmadan İlerleyemez:** `spec_writer`'dan insan onaylı (`session_ended: true` veya onaylı artifact) nihai şartname paketi teslim alınmadan kodlama fazına (`seam_architect` / `coder`) geçilmez.
   - **Çoklu Prototip / Mock Seçimi (Variants):** Birden fazla prototip veya tasarım alternatifi (Variant A/B) istendiğinde, kullanıcı Lavish veya artifact önizlemesi üzerinden tercihini netleştirmeden tekil bir tasarım uygulanamaz.


4. **Kadro Yönetimi & İstasyon Yeniden Kullanım Protokolü (Station Dispatcher):**
   > [!IMPORTANT]
   > İstasyon kuralları ve durum makinesi için doğrudan [**`skills/edge-brigade/SKILL.md`**](../edge-brigade/SKILL.md) ve yatay swarm kuralları için [**`rules/playbooks/swarm-vs-brigade.md`**](../../rules/playbooks/swarm-vs-brigade.md) el kitaplarını referans al.
   
   - **Fil ve Japon Balığı Bellek Modeli (Elephant vs. Goldfish):**
     - 🐘 **Kalıcı Fil İstasyonları (`PERSISTENT_ELEPHANT_ROLES`):** `SPEC_WRITER`, `RESEARCHER`, `SEAM_ARCHITECT`, `CODER`, `SURGEON`, `QA_ENGINEER` — alan bağlamını biriktirir ve YEŞİL bölgede (`< 45k` token) `send_message` ile sürekli yeniden kullanılır.
     - 🐟 **Kısa Ömürlü Japon Balığı İstasyonları (`EPHEMERAL_GOLDFISH_ROLES`):** `EXAMINER` ve `SPEC_CRITIC` — teyit yanlılığını (confirmation bias) yok etmek için her inceleme/eleştiri turunda sıfır konuşma geçmişiyle taze (`invoke_subagent`) türetilir; `orchestrator_guard.py` YEŞİL bölgede dahi taze türetmeye izin verir ve önceki örneği `ROTATED` olarak işaretler.
     - 🧬 **Stratejik Domain Forking (Strategic Context Cherry-Picking):**
       - **`EXAMINER` İnceleme Ajanı:** Domain sözlüğünü ve sözleşme sınırlarını almak için mutlaka `spec_writer` veya `researcher` üzerinden dallandırılır (`fork: "spec_writer"` veya `fork: "researcher"`). Asla `coder` veya `surgeon` geçmişini devralamaz (Examiner Bias Neutrality Invariant — sıfır teyit yanlılığı).
       - **`SPEC_WRITER`:** Çoklu şartname varyantları (N-Spec / Variant A/B) için klonlanabilir.
       - **`RESEARCHER`:** Çoklu hipotez / kök neden araştırmalarında warm handoff ile dallandırılabilir.
     - ⚡ **Kota Koruma Varsayılanı (`Model: "flash"`):** Alt-ajan türetirken (`invoke_subagent`) veya CLI'da istasyon kaydederken (`brigade register --model flash`), insan kaptan açıkça farklı bir model (`pro`, `claude-opus-5-5-high`) talep etmedikçe varsayılan olarak `Model: "flash"` kullanılır.
   - **Station Zero-Amnesia Protocol (Zorunlu İstasyon Yeniden Kullanımı):**
     1. **Önce Kontrol Et:** Bir istasyona iş sevk etmeden önce `manage_subagents(Action: 'list')` veya `brigade stations <repo>` çalıştır.
     2. **Yeniden Kullan (`send_message`):** Hedef rol fil istasyonuysa ve aktif bir çalışan listeleniyorsa, **asla yeni bir `invoke_subagent` çağırma**; doğrudan o ajanın `conversationId`'sini kullanarak `send_message(Recipient: <id>, Message: ...)` ile görevi ilet.
     3. **Yalnızca Yoksa veya Goldfish İse Aç:** Hedef rolde ajan henüz yoksa veya rol goldfish (`EXAMINER`, `SPEC_CRITIC`) ise `invoke_subagent` çağır:
        ```json
        invoke_subagent(
          TypeName: "self",
          Model: "flash",
          Role: "<Kanonik İstasyon Rolü, örn: Seam Architect>",
          Prompt: "<İstasyon Yönergeleri & Görev Detayı>"
        )
        ```
        Dönen `conversationId`'yi hemen `brigade register <repo> --role <role> --conversation-id <id>` ile `.edge/brigade.json`'a kaydet.
     4. **Kanonik İstasyon Zorunluluğu (Ad-Hoc Rol Yasağı):** Asla `Database Operator`, `Quality Worker` gibi ad-hoc roller türetme. 8 Kanonik İstasyon (`SPEC_WRITER`, `SPEC_CRITIC`, `RESEARCHER`, `SEAM_ARCHITECT`, `CODER`, `SURGEON`, `EXAMINER`, `QA_ENGINEER`) kullan. Teslimat ve entegrasyon deterministik CLI (`brigade finish-slice`) ile yürütülür.
   - **İş Akışı Zincirleri:**
     - **Feature İşi:** `SPEC_WRITER` $\rightarrow$ `SPEC_CRITIC` (`brigade critique-spec --native` veya eksik `agy` fallback: Ultra'da `swarm` `spec_critic`, Pro'da `invoke_subagent` `Model: "pro"`) $\rightarrow$ **[ISOLATED WORKTREE GATE]** (`brigade start-slice --track feature` ile `treehouse` birincil veya native `git worktree` fallback peşin kiralama & `RED_TEST`) $\rightarrow$ `SEAM_ARCHITECT` (Worktree'de Kırmızı Test, `brigade advance` ile doğrulama $\rightarrow$ `SURGERY`) $\rightarrow$ `CODER` (Worktree'de Yeşil Test) $\rightarrow$ `GATE` (`tools/gate.py` + UI `diff_image.py`) $\rightarrow$ `[QA_ENGINEER]` (`ProofVerifier` Makbuzu) $\rightarrow$ `EXAMINER` (3-Eksenli Kanıt Odaklı İnceleme + `brigade seal-review`) $\rightarrow$ Deterministik Teslimat (`brigade finish-slice` ile birleştirme, worktree temizliği, şartname arşivleme, `/edge-drift` denetimi, `brigade prepare-ship`).
     - **Refactor İşi:** **[ISOLATED WORKTREE GATE]** $\rightarrow$ `SURGEON` (Worktree'de Cerrahi; Swarm paralel dalında Antigravity `workspace="share"`/`"branch"`) $\rightarrow$ `GATE` (`tools/gate.py` + `ui` izinde `diff_image.py <= 0.15%`) $\rightarrow$ `[QA_ENGINEER]` $\rightarrow$ `EXAMINER` (3-Eksenli İnceleme + `brigade seal-review`) $\rightarrow$ Deterministik Teslimat (`brigade finish-slice`).
     - **Bug-Fix İşi:** `RESEARCHER` (RCA) $\rightarrow$ `SEAM_ARCHITECT` (Karakterizasyon Testi) $\rightarrow$ **[ISOLATED WORKTREE GATE]** $\rightarrow$ `CODER` $\rightarrow$ `GATE` $\rightarrow$ `[QA_ENGINEER]` $\rightarrow$ `EXAMINER` (`brigade seal-review`) $\rightarrow$ Deterministik Teslimat (`brigade finish-slice`).
     - **QA / E2E Doğrulama:** `QA_ENGINEER` (Birincil E2E: yerleşik `browser` Subagent Delegasyonu; görsel eşlik & Fiber: `chrome-devtools-axi` $\rightarrow$ `chrome-devtools-mcp` $\rightarrow$ `browser` fallback + `ProofVerifier` ile SHA-256 Ekran Görüntüsü, Auth-Wall Engeli & `db_crosscheck` Doğrulaması `.edge/qa/proofs/<slug>.json`).
     - **Zorunlu Worktree Temizliği:** `finish-slice` ve `abort` (`edge/aborted/...` commit koruma) iş bitiminde worktree'yi temizler; yetim dizinler `brigade worktree <repo_path> --action prune` ile süpürülür.

5. **Bağlam Isısı & Güvenli Duraklatma (Context Heat Sentinel):**
   - 🟢 **YEŞİL BÖLGE (< 45k token, `GREEN_HEAT_THRESHOLD = 45,000`):** Görüşmeler ve biletlemeler normal seyreder. Fil istasyonları `send_message` ile korunur.
   - 🟡 **SARI BÖLGE (45k - 75k token, `45,000 <= tokens < 75,000`):** Yeni bilet alımı durdurulur (`triage` dondurulur). Aktif iş biter bitmez checkpoint atılır (`python tools/brigade/cli.py pause`).
   - 🔴 **KIRMIZI BÖLGE (>= 75k token, `YELLOW_HEAT_THRESHOLD = 75,000`):** Acil durum dondurması. Mevcut durum `.edge/checkpoint.json`'a yazılır ve taze oturuma devredilir (Zero-Amnesia Pickup).

---

## ⚡ Kullanım ve Komut Akışı (Global `brigade` CLI)

```bash
# 1. Brigade Durumunu İncele
brigade status <repo_path>

# 2. Kalıcı İstasyonları Kaydet (conversation_id ve opsiyonel --model ile, varsayılan: flash)
brigade register <repo_path> --role spec_writer --conversation-id <id> --model flash
brigade register <repo_path> --role seam_architect --conversation-id <id> --model flash
brigade register <repo_path> --role coder --conversation-id <id> --model flash
brigade register <repo_path> --role examiner --conversation-id <id> --model flash
brigade register <repo_path> --role qa_engineer --conversation-id <id> --model flash

# 3. Şartname Danışman Denetimi (Parent Issue SSOT via tools/tracker)
brigade critique-spec <repo_path> --issue <parent_issue>

# 4. Dikey Dilimi Başlat (Parent Issue = Spec SSOT, Child Issue = Ticket)
brigade start-slice <repo_path> --name <slice-adi> --track feature --issue <child_issue> --parent-issue <parent_issue>

# 5. İşi İlerlet (Deterministik Kapılar Geçişi Yönetir: VERIFY -> GATE -> [QA] -> REVIEW -> STAGING)
brigade advance <repo_path>

# 5b. Examiner 3-Eksenli İnceleme Mührü (REVIEW -> STAGING öncesi zorunlu)
brigade seal-review <repo_path> --verdict PASS --summary "<summary>" --evidence-reviewed "<paths>"

# 6. Dikey Dilimi Tamamla (development Dalına Fast-Forward Merge, Şartname Arşivleme & Worktree İadesi)
brigade finish-slice <repo_path>

# 6b. Specs-to-PR Köprüsü (no-mistakes öncesi intent kilitleme ve Pocock/Horthy PR gövdesi üretimi)
brigade prepare-ship <repo_path> --base staging --format pr

# 7. Yaşayan Alan Senetlerini Denetle (Drift Scanner)
python3 tools/drift/cli.py check <repo_path>

# 8. Güvenli Duraklatma (Bağlam Isısı Sebebiyle)
brigade pause <repo_path> --reason CONTEXT_LIMIT_YELLOW
```

---

## 🚫 Negatif Kısıtlar (Anti-Patterns & Deterministic Hook Guards)

> [!CRITICAL]
> **Orkestratör Fiziksel Araç Kalkanı (Hard Tool Gating):**  
> `orchestrator_guard.py` hook'u Orkestratör'ün kaynak/test kodları üzerinde `write_file`, `edit_file` veya `read_file` çağırmasını fiziksel olarak ENGELLER (exit code deny).  
> Kod okuma gerekiyorsa `RESEARCHER`'a, kod yazma gerekiyorsa `SEAM_ARCHITECT`/`CODER`/`SURGEON`'a delege etmek ZORUNLUDUR.

* ❌ **Asla Ana Çalışma Ağacında Kodlama / Cerrahi Yapma (Zero-Touch Primary Invariant):** Feature işlerinde `start-slice` ile worktree peşin kiralanır ve `RED_TEST` durumunda başlatılır. Kırmızı testler dahil tüm kodlama ve cerrahi izole worktree içinde icra edilir; ana repoda doğrudan üretim kodu değiştirmek KESİNLİKLE YASAKTIR.
* ❌ **Asla Orkestratör Bağlamında Kod Üretme:** Cerrahiyi ve kodlamayı istasyon ajanlarına (`coder`, `surgeon`) bırak.
* ❌ **Asla Orkestratör Bağlamında Üretim/Test Kodu Okuma:** Kod analizi için `RESEARCHER` istasyonunu sevk et. Orkestratör yalnızca `.edge/**`, `specs/**`, `coding_standards.md` ve artifact belgelerini okuyabilir.
* ❌ **Asla Mükerrer İstasyon Ajanı Doğurma (Anti-Graveyard):** İlgili rolde aktif veya kayıtlı bir istasyon varsa `invoke_subagent` çağırma; `send_message(Recipient: <id>)` ile iletişimi sürdür.
* ❌ **Asla Ad-Hoc Persona / Rol Türetme:** `Database Operator`, `Quality Worker` gibi keyfi roller açma; yalnızca 8 kanonik Brigade istasyonunu kullan.
* ❌ **Asla UI'ı Onaysız Geçme:** `lavish-axi` prototipi insan tarafından onaylanmadan kodlama fazını başlatma.
* ❌ **Asla Kırmızı Test Olmadan Coder'a İşi Verme:** `seam_architect` fail eden birim testi yazmadan kodlayıcı işe başlayamaz.
* ❌ **Asla E2E Anomalilerini Doğrudan Düzeltmeye Çalışma:** `qa_engineer` bulduğu UI/UX anomalilerini `brigade qa-inspect --frontier` ile `tools/tracker/` (`type:frontier`, `track:ui`) üzerine loglar (`frontier-axi` soft-deprecated), kod tabanını mutasyona uğratmaz.
