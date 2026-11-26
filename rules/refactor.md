# 🧬 Refactoring Domain Protocol & Safety Manual

Bu doküman, otonom ve yarı-otonom refaktör görevlerini icra eden tüm alt-ajanlar (`SURGEON`, `EXAMINER`) için operasyonel rehberdir.

---

## 🎯 Temel Misyon

* **Girdi:** `.edge/ledger/core.json` veya `.edge/ledger/ui.json` defterindeki bilet.
* **Amaç:** Davranışı milimetrik olarak koruyarak, monolitik ve sızıntılı kodları temiz katmanlara ayrıştırmak veya tekrar eden UI yapılarını merkezi primitiflere toplamak.
* **Çıktı:** `MigrationGate`, `Max CC Non-Regression` (maksimum döngüsel karmaşıklık kötüleşmemesi) ve `Layer Leakage Gate` (katman sızıntısı kontrolü) kapılarından geçmiş, testleri yeşil, `gate.py` onaylı atomik git commit.

---

## 🛑 Altın Kurallar (Non-Negotiable)

0. **Zorunlu Treehouse Worktree İzolasyonu (Zero-Touch Primary Invariant):**
   * `SURGEON` ameliyata başlamadan önce İSTİSNASIZ olarak Treehouse üzerinden izole bir worktree kiralanır (`python3 tools/brigade/cli.py start-slice <repo> --name <slice> --track <core|ui>` veya `treehouse get --lease -b refactor/<slice>`).
   * Ana repo çalışma kopyasında (`/home/oguz/<project>`) doğrudan kod düzenlenemez; tüm ameliyat kiralık worktree (`/home/oguz/.treehouse/pool/slot-N/...`) içinde icra edilir.
   * Doğrulama tamamlandığında `python3 tools/brigade/cli.py finish-slice <repo>` ile ana depodaki aktif entegrasyon dalına (Stack Profile `integration` dalı, varsayılan `main`) fast-forward (`git merge --ff-only`) birleştirilir ve worktree havuza iade edilir.

1. **Davranış Değiştirme Yasağı:**
   * Bir fonksiyonun dönüş tipini, parametre sırasını veya dışarıya verdiği cevabı bozamazsın.
   * `if (x)` kontrolünü keyfine göre kaldıramazsın veya değiştiremezsin.
2. **Karakterizasyon ve Regresyon Koruması:**
   * Ameliyata başlamadan önce testleri veya derleyici kontrollerini çalıştır.
   * Testler ve aktif Stack Profile'ın tip/derleme kontrolü (`typecheck`) yeşil olmadan tek satır iş kodu değiştirilemez.
3. **İçten Dışa Adım (Inside-Out):**
   * **Core Track:** Önce domain repository ve saf iş mantığı ayrıştırılır, ardından giriş/kontrolcü katmanı ince bir orkestratöre dönüştürülür (aktif Stack Profile varsa `profiles/<id>/PLAYBOOK.md` uygulanır).
   * **UI Track:** Önce merkezi UI primitifleri (Stack Profile `ui_globs` katmanı) oluşturulur, ardından tekrarlayan ham arayüz blokları bu bileşene taşınarak sığ sarmalayıcılar (`Zero-Wrapper`) silinir.
4. **Deterministik Mimari Kapılar (`MigrationGate`, `Max CC Non-Regression`, `Layer Leakage`):**
   * **`MigrationGate`:** Refaktör sırasında aktif Stack Profile'da tanımlanan şema ve migrasyon dosyalarına (`schema_globs`, `migration_globs`) kesinlikle dokunulmaz.
   * **`Max CC Non-Regression`:** Yapay satır sayısı küçültme (`ΔSLOC < 0`) zorunluluğu uygulanmaz; temiz arayüz ve katman ayrıştırmaları toplam satır sayısını artırabilir. Bunun yerine mevcut dosyalarda maksimum döngüsel karmaşıklık (`Max CC`) kötüleşemez (`after_max_cc <= max(before_max_cc, 10)`) ve yeni üretim dosyalarında `Max CC <= 10` tavanı korunur.
   * **`Layer Leakage Gate`:** Aktif Stack Profile'ın giriş/aksiyon dosyalarında (`action_globs`) doğrudan DB/veri erişimi sızıntısı artamaz (`after_leaks <= before_leaks`) ve yeni giriş dosyalarında `0` olmalıdır.
5. **Tip Güvenliği ve Standart Uyumu:**
   * Projenin `coding_standards.md` dosyasına riayet edilir; `any` veya gevşek tip kaçamakları yasaktır.
6. **Kapı Kontrolü ve 4-Mühürlü `RefactorReceipt` (Gate & Receipt):**
   * Refaktör bileti `brigade create-refactor-ticket` veya `radar export-tasks --parent-issue <P>` ile `target_repo/.edge/tickets/refactor/<slug>.md` ve `tools/tracker` üzerinde (`status:ready`, `--no-sync-tasks` ile atlanabilir; `tasks-axi`/`frontier-axi` soft-deprecated) oluşturulur.
   * Değişiklik bittiğinde `python3 tools/gate.py <repo> --format json` (eksik analizörlerde `null`, asla `0` değil) ve görsel regresyon kontrolleri (UI için `<= 0.15%`) 0 exit code ile geçmelidir.
   * `brigade advance` (`GATE -> REVIEW -> STAGING`) veya `brigade seal-refactor` ile `(commit_sha, changed_files_hash)` bağlı 4-mühürlü `RefactorReceipt` (`.edge/receipts/refactor/<slug>.{json,md}`) üretilir; `examiner_cid != surgeon_cid` nötrlüğü zorunludur.
   * `brigade finish-slice <repo> --pr` One-Way Door tetikleyicilerini (export API kırılması, auth segmentleri, `>15` dosya veya `>500` satır) açık tutar; PR gövdesinde `Closes #<C>` bağlanır ve Two-Way Door auto-merge kuyruklandığında `AWAITING_MERGE` durumuna geçip `brigade confirm-merge <repo>` ile `status:done` + issue close + `IDLE` dönüşü tamamlanır.
