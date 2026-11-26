# 🌟 Feature Delivery Playbook (Unified Brigade Feature Station)

Bu doküman, `edge` eklentisi bünyesinde **Yeni Davranış & Feature Ekleme** operasyonlarını yürüten Unified Brigade hattının deterministik anayasasıdır.

---

## 🎯 1. Kadro İstasyonları & Sorumluluk Dağılımı

1. **ORCHESTRATOR (Yeşil Alan / Mülakat):**
   * Yüksek seviyeli hedef, epik ve kullanıcı hikayelerini tartışır; kod üretmez. Bağlam ısısı Sarı/Kırmızı bölgeye ulaştığında `pause-safely` protokolünü işletir.
2. **SPEC_WRITER (Çevirmenlik & N-Spec Slicing):**
   * Ham hikayeyi net düz İngilizceye çevirir (Ubiquitous Language) ve N-spec işleri dikey dilim mikro-spesifikasyonlarına böler.
   * **Visual Approval Gate (`lavish-axi`):** UI dokunuşlarında `.lavish/<feature>.html` prototipi üretir ve `lavish-axi` üzerinden kullanıcı onayı almadan kodlamaya geçişi başlatmaz (bkz. Bölüm 2.1).
3. **SPEC_CRITIC (Danışman Şartname Denetçisi / Cross-Provider Goldfish):**
   * Şartname mühürlendikten sonra `brigade critique-spec --issue <P> <repo>` ile sıfır bağlamlı eleştiri üretir (bkz. Bölüm 2.2). Danışman kapıdır; FSM'i kilitlemez.
4. **RESEARCHER (Deep Research & RCA):**
   * Kod tabanında bağımlılıkları, çağrı ağaçlarını ve 3. parti API dokümanlarını araştırır. Kod değiştirmez.
5. **SEAM_ARCHITECT (Michael Feathers Seams & Kırmızı Testler):**
   * Seam noktalarını ve arayüz/tip sözleşmelerini (aktif Stack Profile kurallarına göre) tanımlar; kiralık Treehouse worktree içinde (`RED_TEST`) kırmızı birim/kontrat testlerini yazar (`brigade advance` ile `SURGERY` geçişi).
6. **CODER (Kodlayıcı İşçi):**
   * Seam sözleşmelerine sadık kalarak kiralık worktree içinde aktif Stack Profile'ın `source_roots` dizinleri altında üretim kodunu yazar.
   * **Test Dokunulmazlığı (Test Immutability):** Seam Architect'in yazdığı test dosyalarına ASLA dokunamaz, testleri yumuşatamaz.
   * Çıkış kriteri: Aktif Stack Profile (`profiles/<id>/`) tarafından yapılandırılan `unit_test` ve `typecheck` komutlarının exit 0 vermesi.
7. **EXAMINER (Tek Geçişte 3 Eksenli Kanıt Odaklı Denetim):**
   * `GATE` ve (varsa) `QA` sonrasında çalışır (`VERIFY -> GATE -> [QA] -> REVIEW -> STAGING`).
   * **Eksen 1 (`--axis standards`):** `coding_standards.md` kuralları ve Fowler kokuları.
   * **Eksen 2 (`--axis spec`):** Mimari katman sınırları ve kapsam taşması.
   * **Eksen 3 (`--axis evidence`):** `tools/gate.py` sonucu, UI `diff_image.py` farkları (`.edge/qa/visual/<slug>-diff.png`), `ProofVerifier` onaylı `.edge/qa/proofs/<slug>.json` makbuzları ve `db_crosscheck` kanıtlarının şartnameyle tutarlılığı.
   * Çıkışta `brigade seal-review <repo> --verdict PASS|FAIL --summary "..."` zorunludur.
8. **QA_ENGINEER (E2E Browser & Visual QA Sommelier):**
   * **Lavish-Gated QA:** `.lavish/` prototipi veya `--qa` varsa `GATE -> QA -> REVIEW`, saf backend işlerinde `GATE -> REVIEW` yürür (bkz. Bölüm 2.5).
   * **Deterministik `ProofVerifier` Kapısı:** Canlı DOM reload + `db_crosscheck` doğrulanır; `.edge/qa/proofs/<slug>.json` makbuzunda diskte mevcut, sıfır bayt olmayan, benzersiz SHA-256 özetli ekran görüntüleri, auth-wall redirect içermeyen URL'ler ve `host_facts_verified: true` aranır.
9. **Deterministik Teslimat (`brigade finish-slice`, `edge-drift` & `brigade prepare-ship`):**
   * Doğrulanan dalı FSM üzerinden ana depodaki entegrasyon dalına (Stack Profile `delivery.default_stage_branches.integration`, varsayılan `main`) fast-forward birleştirir, worktree'yi iade eder, çocuk alt-bileti `status:done` kapatır (Parent Issue açık kalır) ve `brigade prepare-ship --issue <C> --parent-issue <P>` ile `Closes #<C>` + `Parent Spec: #<P>` PR gövdesini üretir.
   * `.edge/cache/issues/` önbelleği asla arşivlenmez (`INV-CACHE-NO-ARCHIVE`); yalnızca legacy `.edge/specs/<slice>.md` dosyaları `.edge/archive/specs/` altına taşınır.

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
[CODER WORKER]   ──────────────────────► [YEŞİL TEST GATE: profile unit_test (0) & typecheck (0)]
       │
       ▼
[GATE]           ──────────────────────► [EDGE GATE: tools/gate.py = 0 & ui diff_image <= 0.15%]
       │
       ├─────────────────────────────────┐ ("Lavish varsa QA yap, yoksa es geç")
       │ (Lavish prototip / --qa VAR)     │ (Lavish prototip YOK / --no-qa)
       ▼                                 │
[CycleState.QA]  ──────────────────────┐ │
       │ (QA_ENGINEER: ProofVerifier     │ │
       │  SHA-256 + DB + Tier-1 Console) │ │
       ▼                                 ▼ ▼
[EXAMINER]       ──────────────────────► [REVIEW GATE: 3-Axis + `brigade seal-review` PASS]
       │
       ▼
[FINISH-SLICE]   ──────────────────────► [STAGING & DRIFT: git merge --ff-only, spec archival
                                          to .edge/archive/specs/, living deeds via /edge-drift,
                                          Specs-to-PR bridge via `brigade prepare-ship`]
```

### 🛑 2.1 Visual Approval Gate İnvaryantları (No-Bypass Kuralı)
1. **Asla Varsayılan Onay Yoktur:** `.lavish/` prototipi insan tarafından Lavish Editör üzerinden incelenip `Send & End` ile mühürlenmeden onaylanmış sayılamaz.
2. **Spec Writer'ın Doğrudan Döngü Sahipliği:** `SPEC_WRITER`, UI işlerinde prototipi/varyantları `.lavish/` altında üretir, `wsl bash -c "lavish-axi <html-file>"` ile oturum açar, `lavish-axi poll <html-file>` ile kullanıcı notlarını (`--agent-reply`) dinler ve yalnızca `session_ended: true` olduğunda Orkestratör'e teslim eder.
3. **Orkestratör Yeşil Alan İnvaryantı:** Orkestratör yalnızca `session_ended: true` olmuş nihai paketi teslim alır.

### 🛑 2.2 Danışman Şartname Eleştirisi (`brigade critique-spec`)
1. Onaylı Parent Issue (`spec:approved`) üzerinde `brigade critique-spec --issue <P> <repo>` çalıştırılır (legacy `--spec <spec_path>`).
2. Sıfır bağlamlı `claude-opus-5-5-high` (kota aşımında `gemini-3.8-flash-high`) raporu `.edge/cache/issues/<P>-critique.md` dosyasına yazar ve `--no-post-comment` yoksa Issue yorumuna ekler.
3. Danışman niteliklidir; Orkestratör eksik kararları ve yeniden kullanım fırsatlarını kaptana sunar.

### 🛑 2.3 Deterministik Treehouse Worktree & RED_TEST Kapısı (Zero-Touch Invariant)
1. **Peşin Worktree Kiralama:** Test yazımından önce izole worktree kiralanır:
   ```bash
   python3 tools/brigade/cli.py start-slice --issue <C> --parent-issue <P> --name <feature-name> --track feature /home/oguz/<project> [--expected-files ...]
   ```
2. **Kırmızı Test & İzole Kodlama:** `SEAM_ARCHITECT` testleri kiralık worktree'de yazar; `brigade advance` hakiki non-zero assertion hatasını doğrulayıp `SURGERY` durumuna geçirir. `CODER` ana repoda tek bir dosya dahi değiştiremez.

### 🛑 2.4 Şartname Arşivleme ve Yaşayan Alan Senetleri (`edge-drift`)
1. `EXAMINER` onayı sonrası `brigade finish-slice <repo>` çalıştırıldığında, worktree dalı entegrasyon dalına (Stack Profile `integration` dalı, varsayılan `main`) fast-forward (`git merge --ff-only`) birleştirilir, worktree iade edilir ve `.edge/specs/<slice>.md` `.edge/archive/specs/` dizinine arşivlenir.
2. Kalıcı alan senetleri `docs/<domain>/DOMAIN.md` (veya legacy `docs/domains/<domain>.md`) altında saklanır ve `python3 tools/drift/cli.py check <repo>` ile taranır.

### 🛑 2.5 Lavish-Gated QA İnvaryantı (`GATE -> QA -> REVIEW` vs `GATE -> REVIEW`)
1. `CycleState.GATE` sonrasında `fsm.should_run_qa()` çalışır (`track == "ui"` dilimlerinde `diff_image.py <= 0.15%` piksel eşliği doğrulanır). `.lavish/` veya `--qa` varsa `QA` aşamasına, saf backend/motor işlerinde doğrudan `REVIEW` aşamasına geçilir.
2. `CycleState.QA` içinde tespit edilen `console.error`, unhandled exception veya prototip kopukluğu `CRITICAL` sayılır ve FSM'i `POLISH` aşamasına döndürür. Kozmetik pürüzler `brigade qa-inspect --frontier` ile `tools/tracker/` (`type:frontier`, `track:ui`) üzerine journal edilir (`tasks-axi`/`frontier-axi` soft-deprecated).

---

## 🚫 3. Negatif Kısıtlar ve Esneklikler

* ❌ **Satır Küçültme Kısıtı Rafa Kaldırıldı:** Refaktörde uygulanan $\Delta\text{SLOC} < 0$ kuralı Feature hattında uygulanmaz. Kodun temizliği, tiplerin katılığı ve testlerin yeşilliği esastır.
* ❌ **Test Hilesi Yasağı:** Coder ajanı kendi testini kendine yazamaz ve Seam Architect'in testini değiştiremez.
* ❌ **Yarım Bırakılmış Katman Yasağı:** Backend yazılıp arayüz havada bırakılamaz.
* ✅ **Şema Değişikliği İzni:** Gerekli durumlarda `allow_schema_migration: true` ile şema güncellenebilir ve migration dosyası üretilebilir.
