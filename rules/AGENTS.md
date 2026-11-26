# 🛡️ Edge Plugin Core Rules & Tooling Protocol

Bu kurallar, `edge` eklentisini kullanan tüm çalışma alanlarında geçerli evrensel araç hiyerarşisini ve standart belirleme protokolünü yönetir.

---

## 🧭 0. Cross-OS Çalışma Ortamı Doktrini (Cross-OS Runtime Doctrine)
> [!CRITICAL]
> `edge` eklentisi **`windows`**, **`wsl`**, **`macos`** ve **`linux`** ortamlarını eşit olarak destekler (`~/.edge/machine.json`).
> - Ajanlar çalışma ortamını hedef projenin bulunduğu platforma göre çözer (yerel Windows, WSL2, macOS veya native Linux); sabit kullanıcı adı veya tek OS varsayımı yapmaz.
> - Yalnızca Windows ana makinesinden bir WSL2 deposu hedeflendiğinde terminal komutları `wsl --cd <linux_path> ...` üzerinden çalıştırılır.
> - Native Linux, macOS veya yerel Windows projelerinde komutlar doğrudan yerel kabuk ve Python/Node çalışma zamanı üzerinden yürütülür (`tools/common/env.py`, `tools/common/paths.py`).

---

## 🌳 0.1 Zero-Touch Primary Working Tree & İzole Worktree İnvaryantı
> [!CRITICAL]
> **Ana Repo Çalışma Ağacına Doğrudan Kod Yazma Yasağı (Zero-Touch Primary Invariant):**
> İster Feature ister Refactor operasyonu olsun; **kırmızı testleri geçmek için üretim koduna dokunmadan önce (`CODER`)** veya **ameliyat başlatılmadan önce (`SURGEON`)**, her durumda izole bir çalışma ağacı kiralanmalıdır. Worktree Fallback Hiyerarşisi:
> 1. **Antigravity Swarm / Subagent Çalışması:** Yerleşik **`workspace="share"`** (veya A/B izolasyonunda **`workspace="branch"`**) kullanılır; görev tamamlandığında dal/kopya ana çalışma alanına güvenli biçimde birleştirilir (`kill` öncesi).
> 2. **Edge Brigade CLI (`treehouse` Birincil $\rightarrow$ Native `git worktree` Fallback):** `treehouse` kuruluysa havuzdan slot kiralanır; `treehouse` yoksa tüm işletim sistemlerinde (`windows`, `wsl`, `macos`, `linux`) otomatik olarak repo dışı native **`git worktree`** havuzuna (`~/.edge/worktrees/<repo>-<hash6>/<branch>`) düşülür:
> ```bash
> # Yöntem 1 (Önerilen - Brigade Slice; treehouse veya native git worktree fallback seçer):
> brigade start-slice <repo-root> --name <slice-adi> --track <feature|core|ui>
>
> # Yöntem 2 (Doğrudan Treehouse veya Brigade Worktree CLI):
> brigade worktree <repo-root> --action lease --branch feat/<slice-adi>
> ```
> - Ana repo dizini (`<repo-root>`) sadece koordinasyon, biletleme ve git branch takibi içindir; doğrudan üretim kodu mutasyonuyla KİRLETİLEMEZ.
> - Tüm dosya düzenleme (`write_file`, `edit_file`) ile aktif **Stack Profile** (`profiles/<id>/`) tarafından tanımlanan derleme, tip kontrolü ve test koşturma işlemleri kiralık worktree (`<worktree-path>`) içinde icra edilir.
> - **Zorunlu Temizlik (Mandatory Cleanup & Zero-Data-Loss):**
>   - Tamamlanan dilimler `brigade finish-slice <repo>` ile entegrasyon dalına fast-forward (`git merge --ff-only`) birleştirilir, worktree kaldırılır (`git worktree remove` + `prune`) ve yalnızca birleştirilmiş dal `git branch -d` ile silinir (birleşmemiş `--pr` dalları korunur).
>   - İptalde (`brigade abort`) worktree `--force` ile temizlenir; ancak üzerinde yeni commit bulunan dallar asla `git branch -D` ile silinmez, `edge/aborted/<branch>-<timestamp>` dalına taşınır.
>   - Yetim kalan veya yarım kalmış dizinler `brigade worktree <repo> --action prune` ile deterministik olarak temizlenir.

---

## 🧭 1. AXI-First Araç Hiyerarşisi ve Fallback Protokolü

Ajanlar çevre birimleriyle (Git, Tarayıcı, Görev Listesi) etkileşime girerken token tasarrufu ve determinizm adına aşağıdaki öncelik sırasını takip etmekle yükümlüdür:

### 📋 A. Görev & Backlog Yönetimi (GitHub Issues + Sub-issues SSOT)
1. **GitHub Issues + Native Sub-issues (`tools/tracker/` — Birincil):** Tüm epikler (`type:frontier`, `spec:draft` $\rightarrow$ `spec:approved`) ve yürütülebilir dikey dilim alt-biletleri (`status:ready` $\rightarrow$ `status:in-progress` $\rightarrow$ `status:done`) `tools/tracker/cli.py` üzerinden yönetilir (`gh-axi` $\rightarrow$ `gh` fallback; remote yoksa veya `--offline` / `EDGE_TRACKER=local` ile `.edge/issues/` yerel deposu). Uzak kimlik doğrulama/ağ hatasında sessizce `local`'e düşülmez (fail-fast exit `2`).
2. **Legacy `tasks-axi` & `frontier-axi` (Soft-Deprecated):** Yalnızca mevcut/eski biletlerin geriye dönük uyumluluk fallback'i için korunur; yeni şartname, dilim ve QA park kayıtları `tools/tracker/` üzerinden açılır.

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

1. **Önce Proje Standartlarını ve Bağlam Ontolojisini Oku:**
   * Bir göreve başlamadan önce proje kök dizininde `coding_standards.md`, `CONTEXT.md` ve `.agents/rules/` dosyaları aranır.
   * Varsa, tüm kodlama ve terminoloji kararları doğrudan bu belgelerin çizdiği sınırlara göre verilir.

2. **Standart veya Terim Yoksa Uydurma, Mülakat Yap (`/grill*`):**
   * Eğer hedef projede `coding_standards.md` veya `CONTEXT.md` sözlüğü bulunmuyorsa; ajan rastgele varsayımlarda bulunamaz.
   * Kullanıcıyı `/grill-me` veya `/grill-with-docs` becerileriyle mülakata alarak; projenin mimari tercihlerini (`coding_standards.md`) ve kapalı kavram sözlüğünü (`CONTEXT.md`) netleştirir.

---

## 📚 3. Operasyonel El Kitapçıkları (Playbook Routing)

Ajanlar icra ettikleri görevin niteliğine göre ilgili kılavuzu referans almalıdır:

* 🧭 **Bağlam Sistemi & Ontoloji Anayasası (Context System Constitution):**  
  System Triad, Diátaxis mod ayrımı, `CONTEXT.md`, `docs/<domain>/DOMAIN.md` ve 1–3 satırlık kod ön-bilgisi kuralları için [**`rules/context-system.md`**](rules/context-system.md) belgesini oku.

* 🧬 **Refaktör Görevleri (Yapısal Değişim, Sıfır Davranış Değişimi):**  
  Detaylı yönergeler için [**`rules/refactor.md`**](rules/refactor.md) el kitabını oku.  
  *(Özet: Davranış sabittir, önce karakterizasyon testi doğrulanır, içten dışa icra edilir, bütçe daralması aranır).*

* 🌟 **Feature Görevleri (Yeni Yetenek, Davranış Değişimi):**  
  Detaylı yönergeler için [**`rules/feature.md`**](rules/feature.md) el kitabını oku.  
  *(Özet: Dıştan içe icra edilir, kabul kriterleri ve spec-wise review esastır).*

* ⏸️ **Oturum Duraklatma (Pause-Safely & Context Heat):**  
  Bağlam sınırı yaklaştığında veya kullanıcı dur dediğinde [**`rules/playbooks/pause-safely.md`**](rules/playbooks/pause-safely.md) kılavuzunu uygula.

* ▶️ **Oturum Devralma (Session-Pickup & Zero-Amnesia):**  
  Yeni bir oturum açıldığında transkript okumadan durumu devralmak için [**`rules/playbooks/session-pickup.md`**](rules/playbooks/session-pickup.md) kılavuzunu uygula.

* 📖 **Domain Operasyonel El Kitapçıkları (Distilled Playbooks):**  
  Belirli bir domain veya proje üzerinde çalışmaya başlamadan önce varsa `.edge/stations/<role>.md` yerel istasyon katmanını oku. Tamamlanan bilet sonrası `/edge-distill` ile güncel bilgi damıtılır.

* 🐝 **Swarm vs. Brigade Playbook (Kolektif Çalışma & Yatay Bölümleme):**  
  Detaylı yönergeler için [**`rules/playbooks/swarm-vs-brigade.md`**](rules/playbooks/swarm-vs-brigade.md) el kitabını oku.  
  *(Özet: Dikey özellikler ve kontrat değişimleri Brigade'de; yatay/sharded refaktör, A/B mimari denemeler ve çok açılı RCA Swarm'da icra edilir).*

---

## 🧭 4. Önerilen Beceriler Protokolü (Suggested Skills Protocol)

Eğer çağrılan veya devrede olan bir becerinin frontmatter'ında `suggested_skills` alanı tanımlanmışsa ya da dokümantasyonunda bağımlı becerilere doğrudan atıf yapılmışsa (örneğin `/edge-orchestrator` $\rightarrow$ `edge-brigade`):
1. Ajan, işlem veya alt-ajan sevkine başlamadan önce bu önerilen becerilerin `SKILL.md` dosyalarını derhal okur ve içselleştirir.
2. Tüm kadro yönetimi, alt-ajan dispatch adımları ve durum geçişleri, hem ana becerinin hem de `suggested_skills` ile gelen yönergelerin birleşik prensiplerine göre icra edilir.

