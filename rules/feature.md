# 🌟 Feature Delivery Playbook (Unified Brigade Feature Station)

Bu doküman, `edge` eklentisi bünyesinde **Yeni Davranış & Feature Ekleme** operasyonlarını yürüten Unified Brigade hattının deterministik anayasasıdır.

---

## 🎯 1. Kadro İstasyonları & Sorumluluk Dağılımı

1. **ORCHESTRATOR (Yeşil Alan / Mülakat):**
   * Kullanıcıyla yüksek seviyeli hedefi, epic ve kullanıcı hikayelerini tartışır.
   * Kod üretmez, bağlam penceresini temiz tutar. Bağlam ısısı Sarı/Kırmızı bölgeye ulaştığında `pause-safely` protokolünü işletir.
2. **SPEC_WRITER (Çevirmenlik & N-Spec Slicing):**
   * Kullanıcının anlattığı ham hikayeyi 3-4 cümlelik kristal netlikte düz İngilizceye çevirir (Ubiquitous Language).
   * Büyük hikayeleri (N-spec) dikey dilim mikro-spesifikasyonlarına böler.
   * **Visual Approval Gate (`lavish-axi` Direct Ownership):** UI katmanına dokunulacaksa, `.lavish/<feature>.html` prototipi üretilir, `lavish-axi <file>` ile session URL'i açılır ve bizzat `SPEC_WRITER` `lavish-axi poll <file>` çalıştırarak kullanıcı geri bildirimini/onayını dinler ve revizyonları işler. Kullanıcı tarayıcıdan "Send & End" ile onay vermeden kodlamaya geçiş **KESİNLİKLE YASAKTIR**.
3. **SPEC_CRITIC (Danışman Şartname Denetçisi / Cross-Provider Goldfish):**
   * Şartname mühürlendikten sonra (ve UI varsa `lavish-axi` onayı sonrası), Orkestratör `brigade critique-spec <repo> --spec <spec_path>` çalıştırır.
   * Sıfır bağlamlı ve salt-okunur `claude-opus-5-5-high` (kota aşımında otomatik `gemini-3.8-flash-high` fallback) modeli çağrılır ve `.edge/specs/<stem>-critique.md` raporu üretilir.
   * **Danışman (Advisory) Kapı:** FSM'i kilitlemez; Orkestratör anti-borç, yeniden kullanılabilirlik ve eksik karar uyarılarını insan kaptana özetler.
4. **RESEARCHER (Deep Research & RCA):**
   * Kod tabanında bağımlılıkları, çağrı ağaçlarını inceler. Gerekirse web üzerinden 3. parti API dokümanlarını araştırır. Kod değiştirmez.
5. **SEAM_ARCHITECT (Michael Feathers Seams & Kırmızı Testler):**
   * Seam noktalarını tespit eder, TypeScript interface sözleşmelerini tanımlar.
   * Upfront kiralanan izole Treehouse worktree içinde (`RED_TEST` durumunda) kabul kriterlerini doğrulayan birim/kontrat testlerini yazar.
   * `brigade advance` deterministik olarak hakiki non-zero assertion hatasını doğrular (sözdizimi hatası veya pass-before-code durumunu engeller) ve FSM'i `SURGERY` aşamasına ilerletir.
6. **CODER (Kodlayıcı İşçi):**
   * Seam sözleşmelerine sadık kalarak kiralık worktree içinde `src/` altında üretim kodunu yazar.
   * **Test Dokunulmazlığı (Test Immutability):** Seam Architect'in yazdığı test dosyalarına ASLA dokunamaz, testleri yumuşatamaz.
   * Çıkış kriteri: Kırmızı testleri YEŞİLE çevirmek (`vitest` exit 0) ve `npx tsc --noEmit` exit 0.
7. **EXAMINER (Tek Geçişte Çift Eksenli Denetim):**
   * `coding_standards.md` kurallarını, Fowler kokularını ve 3-tier decoupling mimarisini/kapsam sınırlarını tek geçişte denetler. 0 kritik bulgu aranır.
8. **Deterministik Teslimat (`brigade finish-slice` & `edge-drift`):**
   * Doğrulanan dalı FSM üzerinden ana depodaki `development` dalına fast-forward birleştirir, worktree'yi havuza iade eder ve `no-mistakes` kapısıyla PR'a hazırlar.
   * Geçici dilim şartnamesini (`.edge/specs/<slice>.md`) otomatik olarak `.edge/archive/specs/` dizinine arşivler.
   * Yaşayan alan sözleşmeleri `docs/domains/<domain>.md` altında saklanır ve `/edge-drift` (`python3 tools/drift/cli.py check <repo>`) ile değişmeyen alanlarda sıfır token israfıyla mimari sapma denetimine tabi tutulur.

---

## 🛡️ 2. Deterministik Kapılar (Feature Transition Gates)

```
[İntake / Story]
       │
       ▼
[SPEC_WRITER] ───(UI dokunuşu varsa)───► [lavish-axi GATE: Tarayıcı Onayı]
       │                                              │ (Kullanıcı Onayladı)
       ▼                                              ▼
[SPEC_CRITIC] ─────────────────────────► [ADVISORY CRITIQUE: brigade critique-spec]
       │                                 (claude-opus-5-5-high / gemini-3.8-flash-high)
       ▼
[START-SLICE] ─────────────────────────► [TREEHOUSE WORKTREE GATE: İzole Slot & RED_TEST]
       │                                 (Zero-Touch Primary Invariant Peşin Sağlanır)
       ▼
[SEAM_ARCHITECT] ──────────────────────► [KIRMIZI TEST GATE: brigade advance]
       │                                 (Hakiki non-zero fail doğrulaması -> SURGERY)
       ▼
[CODER WORKER]   ──────────────────────► [YEŞİL TEST GATE: vitest PASS (0) & tsc (0)]
       │
       ▼
[EXAMINER]       ──────────────────────► [REVIEW GATE: 0 Critical Findings]
       │
       ▼
[FINISH-SLICE]   ──────────────────────► [STAGING & DRIFT: git merge --ff-only, spec archival
                                          to .edge/archive/specs/, living deeds via /edge-drift]
```

### 🛑 2.1 Visual Approval Gate İnvaryantları (No-Bypass Kuralı)
1. **Asla Varsayılan Onay Yoktur:** SPEC_WRITER'ın ürettiği HTML prototip, insan tarafından Lavish Editör üzerinden doğrudan incelenip `Send & End` ile mühürlenmeden ASLA onaylanmış sayılamaz. Metin üzerinden "onaylıyorum" denilse dahi canlı Lavish oturumu çalıştırılmalıdır.
2. **Spec Writer'ın Doğrudan Döngü Sahipliği (Direct Ownership Loop):** 
   `SPEC_WRITER`, UI içeren işlerde İSTİSNASIZ olarak:
   - Adım A: Prototipi veya varyantları `.lavish/` altında üretir.
   - Adım B: `wsl bash -c "lavish-axi <html-file>"` ile HTTP session linkini oluşturur ve duyurur.
   - Adım C: `lavish-axi poll <html-file>` ile bekleme moduna geçer.
   - Adım D: Kullanıcı not girdikçe (`session_ended: false`) dosyayı ve şartnameyi günceller, `--agent-reply` ile yanıt verip dinlemeye devam eder.
   - Adım E: Kullanıcı "Send & End" mühürlemesi yaptığında (`session_ended: true`), nihai onaylı şartnameyi Orkestratör'e teslim eder.
3. **Orkestratör Yeşil Alan İnvaryantı:** Orkestratör prototip revizyonlarıyla bağlamını kirletmez. Yalnızca insan tarafından onaylanmış (`session_ended: true`) nihai paketi teslim aldığında bir sonraki istasyona geçiş izni verir.
4. **Çoklu Prototip / Mock Seçimi (Variants):**
   Kullanıcı birden fazla mock/tasarım istediğinde, `SPEC_WRITER` varyantları hazırlar. Kullanıcı Lavish Editor üzerinden seçimini tamamlamadan bir sonraki istasyona geçiş KESİNLİKLE YASAKTIR.

### 🛑 2.2 Danışman Şartname Eleştirisi (`brigade critique-spec`)
1. **Çapraz Sağlayıcı Goldfish Eleştirisi:** `SPEC_WRITER` şartnameyi mühürledikten sonra (ve UI varsa `lavish-axi` mührü sonrası), Orkestratör `brigade critique-spec <repo> --spec <spec_path>` komutunu çalıştırır.
2. **Model Kademesi:** Sıfır bağlamlı ve salt-okunur `claude-opus-5-5-high` modeli çağrılır; kota aşımı durumunda otomatik olarak `gemini-3.8-flash-high` modeline fallback yapar. Rapor atomik olarak `.edge/specs/<stem>-critique.md` dosyasına yazılır.
3. **Danışman (Advisory) Nitelik:** Bu kapı FSM'i sert bir şekilde kilitlemez. Orkestratör, şartnamedeki eksik kararları, yetim kalabilecek yapıları ve mevcut kodun yeniden kullanılabilirliğini insan kaptana danışmanlık olarak sunar.

### 🛑 2.3 Deterministik Treehouse Worktree & RED_TEST Kapısı (Zero-Touch Invariant)
1. **Peşin Worktree Kiralama:** Ana depoda doğrudan üretim kodu yazma yasağı (Zero-Touch Primary Invariant) uyarınca, test yazımına başlamadan ÖNCE Treehouse üzerinden izole bir worktree kiralanır:
   ```bash
   python3 tools/brigade/cli.py start-slice /home/oguz/<project> --name <feature-name> --track feature [--expected-files ...] [--spec ...]
   ```
   Bu komut izole bir worktree slotu kiralar ve FSM'i doğrudan `RED_TEST` durumunda başlatır.
2. **Kırmızı Test Doğrulaması:** `SEAM_ARCHITECT` sözleşmeleri ve kırmızı testleri kiralık worktree (`/home/oguz/.treehouse/pool/slot-N/...`) içinde yazar. `brigade advance` deterministik olarak hakiki non-zero assertion hatasını doğrular (sözdizimi hatası veya pass-before-code durumunu engeller) ve FSM'i `CODER` için `SURGERY` aşamasına ilerletir.
3. **CODER Yalnızca Worktree İçinde Çalışır:** `CODER` ajanı ana repo çalışma dizininde (`/home/oguz/<project>`) tek bir dosya dahi değiştiremez. Tüm kod yazımı, derleme ve yeşil test doğrulaması kiralık worktree içinde icra edilir.

### 🛑 2.4 Şartname Arşivleme ve Yaşayan Alan Senetleri (`edge-drift`)
1. **İskele Şartname Arşivi:** `EXAMINER` onayı sonrası `brigade finish-slice <repo>` çalıştırıldığında, worktree dalı `development` dalına fast-forward (`git merge --ff-only`) birleştirilir, worktree havuza iade edilir ve tamamlanan geçici dilim şartnamesi (`.edge/specs/<slice>.md`) otomatik olarak `.edge/archive/specs/` dizinine arşivlenir.
2. **Yaşayan Alan Senetleri (Living Domain Deeds):** Kalıcı alan kuralları `docs/domains/<domain>.md` altında saklanır (YAML frontmatter'da `tracked_paths` içerir).
3. **Sıfır Token İsraflı Sapma Denetimi:** Bu yaşayan alan senetleri `/edge-drift` (`python3 tools/drift/cli.py check <repo>`) ile taranır; git diff sayesinde değişmeyen alanlar için token harcanmaz ve mimari sapma (drift) anında tespit edilir.


---

## 🚫 3. Negatif Kısıtlar ve Esneklikler

* ❌ **Satır Küçültme Kısıtı Rafa Kaldırıldı:** Refaktörde uygulanan $\Delta\text{SLOC} < 0$ kuralı Feature hattında uygulanmaz. Kodun temizliği, tiplerin katılığı ve testlerin yeşilliği esastır.
* ❌ **Test Hilesi Yasağı:** Coder ajanı kendi testini kendine yazamaz ve Seam Architect'in testini değiştiremez.
* ❌ **Yarım Bırakılmış Katman Yasağı:** Backend yazılıp UI havada bırakılamaz.
* ✅ **Şema Değişikliği İzni:** Gerekli durumlarda `allow_schema_migration: true` ile şema güncellenebilir ve migration dosyası üretilebilir.
