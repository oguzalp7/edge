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

3. **RESEARCHER (Deep Research & RCA):**
   * Kod tabanında bağımlılıkları, çağrı ağaçlarını inceler. Gerekirse web üzerinden 3. parti API dokümanlarını araştırır. Kod değiştirmez.
4. **SEAM_ARCHITECT (Michael Feathers Seams & Kırmızı Testler):**
   * Seam noktalarını tespit eder, TypeScript interface sözleşmelerini tanımlar.
   * **TDD Kırmızı Test Çapası:** İlgili kabul kriterlerini doğrulayan birim/kontrat testlerini yazar ve testin BAŞARISIZ olduğunu (`vitest` exit $\neq$ 0) kanıtlar. Testler kırmızı olmadan kodlayıcıya devredilemez.
5. **CODER (Kodlayıcı İşçi):**
   * Seam sözleşmelerine sadık kalarak `src/` altında üretim kodunu yazar.
   * **Test Dokunulmazlığı (Test Immutability):** Seam Architect'in yazdığı test dosyalarına ASLA dokunamaz, testleri yumuşatamaz.
   * Çıkış kriteri: Kırmızı testleri YEŞİLE çevirmek (`vitest` exit 0) ve `npx tsc --noEmit` exit 0.
6. **EXAMINER (Tek Geçişte Çift Eksenli Denetim):**
   * `coding_standards.md` kurallarını, Fowler kokularını ve 3-tier decoupling mimarisini/kapsam sınırlarını tek geçişte denetler. 0 kritik bulgu aranır.
7. **Deterministik Teslimat (`brigade finish-slice`):**
   * Doğrulanan dalı FSM üzerinden ana depodaki `development` dalına fast-forward birleştirir, worktree'yi havuza iade eder ve `no-mistakes` kapısıyla PR'a hazırlar.

---

## 🛡️ 2. Deterministik Kapılar (Feature Transition Gates)

```
[İntake / Story]
       │
       ▼
[SPEC_WRITER] ───(UI dokunuşu varsa)───► [lavish-axi GATE: Tarayıcı Onayı]
       │                                              │ (Kullanıcı Onayladı)
       ▼                                              ▼
[SEAM_ARCHITECT] ──────────────────────► [KIRMIZI TEST GATE: vitest FAIL (Kırmızı)]
       │
       ▼
[TREEHOUSE WORKTREE GATE] ─────────────► [İzole Worktree Kiralandı: slot-N]
       │
       ▼
[CODER WORKER]   ──────────────────────► [YEŞİL TEST GATE: vitest PASS (0) & tsc (0)]
       │
       ▼
[EXAMINER]       ──────────────────────► [REVIEW GATE: 0 Critical Findings]
       │
       ▼
[FINISH-SLICE]   ──────────────────────► [STAGING: git merge --ff-only into development & return worktree]
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
3. **Orkestratör Yeşil Alan İnvaryantı:** Orkestratör prototip revizyonlarıyla bağlamını kirletmez. Yalnızca insan tarafından onaylanmış (`session_ended: true`) nihai paketi teslim aldığında bir sonraki istasyona (`seam_architect`) geçiş izni verir.
4. **Çoklu Prototip / Mock Seçimi (Variants):**
   Kullanıcı birden fazla mock/tasarım istediğinde, `SPEC_WRITER` varyantları hazırlar. Kullanıcı Lavish Editor üzerinden seçimini tamamlamadan `SEAM_ARCHITECT` veya `CODER` istasyonuna geçiş KESİNLİKLE YASAKTIR.

### 🛑 2.2 Deterministik Treehouse Worktree İzolasyon Kapısı (Zero-Touch Invariant)
1. **Kırmızı Test Sonrası Zorunlu Worktree Açma:** `SEAM_ARCHITECT` sözleşmeleri ve kırmızı testleri oluşturduktan sonra, `CODER` koda dokunmadan ÖNCE İSTİSNASIZ olarak Treehouse üzerinden izole bir worktree kiralanır:
   ```bash
   python3 tools/brigade/cli.py start-slice /home/oguz/<project> --name <feature-name> --track feature
   ```
2. **CODER Yalnızca Worktree İçinde Çalışır:** `CODER` ajanı ana repo çalışma dizininde (`/home/oguz/<project>`) tek bir dosya dahi değiştiremez. Tüm kod yazımı, derleme ve yeşil test doğrulaması kiralık worktree (`/home/oguz/.treehouse/pool/slot-N/...`) içinde icra edilir.
3. **Senkronizasyon & İade:** `EXAMINER` incelemesi tamamlandığında `python3 tools/brigade/cli.py finish-slice <repo>` çalıştırılarak worktree branch'i ana depodaki `development` dalına fast-forward (`git merge --ff-only`) birleştirilir ve worktree slotu Treehouse havuzuna iade edilir.


---

## 🚫 3. Negatif Kısıtlar ve Esneklikler

* ❌ **Satır Küçültme Kısıtı Rafa Kaldırıldı:** Refaktörde uygulanan $\Delta\text{SLOC} < 0$ kuralı Feature hattında uygulanmaz. Kodun temizliği, tiplerin katılığı ve testlerin yeşilliği esastır.
* ❌ **Test Hilesi Yasağı:** Coder ajanı kendi testini kendine yazamaz ve Seam Architect'in testini değiştiremez.
* ❌ **Yarım Bırakılmış Katman Yasağı:** Backend yazılıp UI havada bırakılamaz.
* ✅ **Şema Değişikliği İzni:** Gerekli durumlarda `allow_schema_migration: true` ile şema güncellenebilir ve migration dosyası üretilebilir.
