# 🛡️ Edge Plugin Core Rules & Tooling Protocol

Bu kurallar, `edge` eklentisini kullanan tüm çalışma alanlarında geçerli evrensel araç hiyerarşisini ve standart belirleme protokolünü yönetir.

---

## 🐧 0. Kritik Çalışma Ortamı: WSL2-First Doktrini
> [!CRITICAL]
> Kullanıcı **İSTİSNASIZ** olarak tüm projelerini **WSL2** (`/home/oguz/...`) ortamında yürütmektedir.
> - Ajanlar asla doğrudan Windows `cmd.exe`, `powershell.exe` veya Windows `python.exe` varsayımıyla proje dosyalarına yaklaşamaz.
> - Proje dizinleri daima WSL path'leridir (`/home/oguz/<project>`).
> - Antigravity üzerinden terminal komutları koşulurken daima `wsl bash -c "cd /home/oguz/<project> && ..."` veya WSL alt kabuğu kullanılmalıdır.
> - Windows geçici dizinlerinde proje kodu aranmaz veya çalıştırılmaz.

---

## 🧭 1. AXI-First Araç Hiyerarşisi ve Fallback Protokolü

Ajanlar çevre birimleriyle (Git, Tarayıcı, Görev Listesi) etkileşime girerken token tasarrufu ve determinizm adına aşağıdaki öncelik sırasını takip etmekle yükümlüdür:

### 📋 A. Görev & Backlog Yönetimi
1. **`tasks-axi` (Birincil):** Kabul kriterleri ve dikey sınırları netleşmiş, derhal başlanabilecek iş paketleri için kullanılır. Çıktı token maliyeti neredeyse sıfırdır (`ready`, `done`).
2. **`frontier-axi` (İkincil / Otopark):** Henüz derinleştirilmemiş, bilişsel sis barındıran veya mimari tartışma gerektiren ham fikirlerin park alanıdır. Kabul kriteri netleşmeyen hiçbir iş `tasks-axi`'ye aktarılamaz.

### 🐙 B. Sürüm Kontrolü ve GitHub İşlemleri
1. **`gh-axi` (Birincil):** AXI standardında hafif siklet GitHub CLI köprüsü.
2. **`gh` CLI (Fallback 1):** Standart GitHub CLI aracı (`run_command` üzerinden).
3. **`github-mcp-server` (Fallback 2):** Doğrudan API çağrıları için MCP araç seti.

### 🌐 C. Tarayıcı Otomasyonu ve Görsel Doğrulama (Visual QA)
1. **`chrome-dev-tools-axi` (Birincil):** Headless ve token-tasarruflu görsel regresyon / snapshot aracı.
2. **`chrome-devtools-mcp` (Fallback 1):** Antigravity bünyesindeki MCP araç seti (`navigate_page`, `take_screenshot` vb.).
3. **Sistem CLI / Puppeteer (Fallback 2):** Linux/WSL ortamında çalışan yerel tarayıcı betikleri.

---

## 📖 2. Standart Belirleme ve Mülakat Protokolü (Standards & Grilling)

> [!IMPORTANT]
> **Proje Bağımsızlığı İlkesi:**  
> Kodlama kuralları, dosya yerleşimi ve mimari tercihler projeden projeye değişkenlik gösterir. `edge` eklentisi kafasına göre evrensel bir kod stili dayatamaz.

1. **Önce Proje Standartlarını Oku:**
   * Bir göreve başlamadan önce proje kök dizininde `coding_standards.md` veya `.agents/rules/` dosyası aranır.
   * Varsa, tüm kodlama kararları doğrudan bu dosyanın çizdiği sınırlara göre verilir.

2. **Standart Yoksa Uydurma, Mülakat Yap (`/grill*`):**
   * Eğer hedef projede bir `coding_standards.md` bulunmuyorsa; ajan rastgele varsayımlarda bulunamaz.
   * Kullanıcıyı `/grill-me` veya `/grill-with-docs` becerileriyle mülakata alarak; projenin mimari tercihlerini (dil sürümleri, tip katılığı, klasör hiyerarşisi, test ekolü) netleştirir ve `coding_standards.md` belgesini oluşturur.

---

## 📚 3. Operasyonel El Kitapçıkları (Playbook Routing)

Ajanlar icra ettikleri görevin niteliğine göre ilgili kılavuzu referans almalıdır:

* 🧬 **Refaktör Görevleri (Yapısal Değişim, Sıfır Davranış Değişimi):**  
  Detaylı yönergeler için [**`rules/refactor.md`**](file:///C:/Users/oguz_/.gemini/config/plugins/edge/rules/refactor.md) el kitabını oku.  
  *(Özet: Davranış sabittir, önce karakterizasyon testi doğrulanır, içten dışa icra edilir, bütçe daralması aranır).*

* 🌟 **Feature Görevleri (Yeni Yetenek, Davranış Değişimi):**  
  Detaylı yönergeler için [**`rules/feature.md`**](file:///C:/Users/oguz_/.gemini/config/plugins/edge/rules/feature.md) el kitabını oku.  
  *(Özet: Dıştan içe icra edilir, kabul kriterleri ve spec-wise review esastır).*

* ⏸️ **Oturum Duraklatma (Pause-Safely & Context Heat):**  
  Bağlam sınırı yaklaştığında veya kullanıcı dur dediğinde [**`rules/playbooks/pause-safely.md`**](file:///C:/Users/oguz_/.gemini/config/plugins/edge/rules/playbooks/pause-safely.md) kılavuzunu uygula.

* ▶️ **Oturum Devralma (Session-Pickup & Zero-Amnesia):**  
  Yeni bir oturum açıldığında transkript okumadan durumu devralmak için [**`rules/playbooks/session-pickup.md`**](file:///C:/Users/oguz_/.gemini/config/plugins/edge/rules/playbooks/session-pickup.md) kılavuzunu uygula.

* 📖 **Domain Operasyonel El Kitapçıkları (Distilled Playbooks):**  
  Belirli bir domain üzerinde çalışmaya başlamadan önce varsa `rules/playbooks/generated/<domain>-playbook.md` el kitabını oku. Tamamlanan bilet sonrası `brigade distill <repo>` ile güncel bilgi damıtılır.

---

## 🧭 4. Önerilen Beceriler Protokolü (Suggested Skills Protocol)

Eğer çağrılan veya devrede olan bir becerinin frontmatter'ında `suggested_skills` alanı tanımlanmışsa ya da dokümantasyonunda bağımlı becerilere doğrudan atıf yapılmışsa (örneğin `/edge-orchestrator` $\rightarrow$ `edge-brigade`):
1. Ajan, işlem veya alt-ajan sevkine başlamadan önce bu önerilen becerilerin `SKILL.md` dosyalarını derhal okur ve içselleştirir.
2. Tüm kadro yönetimi, alt-ajan dispatch adımları ve durum geçişleri, hem ana becerinin hem de `suggested_skills` ile gelen yönergelerin birleşik prensiplerine göre icra edilir.

