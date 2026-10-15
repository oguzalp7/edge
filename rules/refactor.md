# 🧬 Refactoring Domain Protocol & Safety Manual

Bu doküman, otonom ve yarı-otonom refaktör görevlerini icra eden tüm alt-ajanlar (`SURGEON`, `STANDARDS_EXAMINER`) için operasyonel rehberdir.

---

## 🎯 Temel Misyon

* **Girdi:** `.edge/ledger/core.json` veya `.edge/ledger/ui.json` defterindeki bilet.
* **Amaç:** Davranışı milimetrik olarak koruyarak, monolitik ve sızıntılı kodları temiz katmanlara ayrıştırmak veya tekrar eden UI yapılarını merkezi primitiflere toplamak.
* **Çıktı:** Net satır sayısı azalmış, testleri yeşil, `gate.py` onaylı atomik git commit.

---

## 🛑 Altın Kurallar (Non-Negotiable)

0. **Zorunlu Treehouse Worktree İzolasyonu (Zero-Touch Primary Invariant):**
   * `SURGEON` ameliyata başlamadan önce İSTİSNASIZ olarak Treehouse üzerinden izole bir worktree kiralanır (`python3 tools/brigade/cli.py start-slice <repo> --name <slice> --track <core|ui>` veya `treehouse get --lease -b refactor/<slice>`).
   * Ana repo çalışma kopyasında (`/home/oguz/<project>`) doğrudan kod düzenlenemez; tüm ameliyat kiralık worktree (`/home/oguz/.treehouse/pool/slot-N/...`) içinde icra edilir.
   * Doğrulama tamamlandığında `python3 tools/brigade/cli.py finish-slice <repo>` ile ana depodaki `development` dalına fast-forward (`git merge --ff-only`) birleştirilir ve worktree havuza iade edilir.

1. **Davranış Değiştirme Yasağı:**
   * Bir fonksiyonun dönüş tipini, parametre sırasını veya dışarıya verdiği cevabı bozamazsın.
   * `if (x)` kontrolünü keyfine göre kaldıramazsın veya değiştiremezsin.
2. **Karakterizasyon ve Regresyon Koruması:**
   * Ameliyata başlamadan önce testleri veya derleyici kontrollerini çalıştır.
   * Testler ve derleyici (`tsc --noEmit`) yeşil olmadan tek satır iş kodu değiştirilemez.
3. **İçten Dışa Adım (Inside-Out):**
   * **Core Track:** Önce domain repository ve saf iş mantığı ayrıştırılır, ardından controller/action ince bir orkestratöre dönüştürülür (`skills/edge-core-refactor`).
   * **UI Track:** Önce merkezi primitif (`src/components/ui/`) oluşturulur, ardından ham JSX blokları bu bileşene taşınarak sığ sarmalayıcılar (`Zero-Wrapper`) silinir (`skills/edge-ui-refactor`).
4. **Tip Güvenliği ve Standart Uyumu:**
   * Projenin `coding_standards.md` dosyasına riayet edilir; `any` veya gevşek tip kaçamakları yasaktır.
5. **Kapı Kontrolü (Gate Execution):**
   * Değişiklik bittiğinde `python tools/gate.py <repo>` ve görsel regresyon kontrolleri (UI için) 0 exit code ile geçmelidir.
