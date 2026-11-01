# 📖 Edge Operating Instructions & Station Navigation Guide

> **"Tek Bir Komutla Bütün Mutfak: Sadece `/edge-orchestrator` becerisine atıfta bulunarak 9 kanonik istasyonu, deterministik kapıları ve test döngülerini yönetin."**

Bu kılavuz, Edge eklentisini kullanan geliştiriciler ve ajanlar için operasyonel el kitabıdır. Kullanıcı tek tek alt-ajanları, test koşucularını veya refaktör komutlarını elle yönetmek zorunda kalmaz; tüm mutfak akışı **`/edge-orchestrator`** üzerinden deterministik olarak sevk edilir.

---

## 📑 İçindekiler
1. [Hızlı Başlangıç: Tek Komut Doktrini](#1-hızlı-başlangıç-tek-komut-doktrini)
2. [İstasyonlar Arası Gezinme ve İş Akışları](#2-istasyonlar-arası-gezinme-ve-iş-akışları)
3. [Antigraveyard & Otomatik Vardiya Değişimi](#3-antigraveyard--otomatik-vardiya-değişimi)
4. [UI Onay Kapısı (`lavish-axi`)](#4-ui-onay-kapısı-lavish-axi)
5. [TDD ve Test İntizamı (Test Immutability)](#5-tdd-ve-test-intizamı-test-immutability)
6. [CLI Araçları ve Teşhis Komutları](#6-cli-araçları-ve-teşhis-komutları)
7. [Proje Standartları Belirleme (`coding_standards.md`)](#7-proje-standartları-belirleme-coding_standardsmd)

---

## 1. Hızlı Başlangıç: Tek Komut Doktrini

Sistemi devreye sokmak için sohbette sadece orkestratörü çağırmanız yeterlidir:

```text
/edge-orchestrator
```

### Sovereign Commander Neler Yapar?
1. **İntake Mülakatı:** Size yeni bir özellik (feature), refaktör veya hata ayıklama (bug-fix) üzerinde mi çalıştığınızı sorar veya hedefinizi INVEST kriterlerine göre dikey dilimlere (DB $\rightarrow$ Core $\rightarrow$ API $\rightarrow$ UI) ayırır.
2. **Bilişsel Sisi Dağıtır:** Belirsiz gereksinimleri `/grill-me` protokolüyle netleştirir.
3. **Yeşil Alanı Korur:** Orkestratör kendi bağlam penceresini devasa diff'lerle şişirmez; görevi ilgili istasyon çalışanına (`SPEC_WRITER`, `SEAM_ARCHITECT`, `CODER`, `SURGEON`, `QA_ENGINEER`) delege eder.

---

## 2. İstasyonlar Arası Gezinme ve İş Akışları

Orkestratör, görevin türüne göre istasyonları sırayla devreye sokar:

### 🌟 A. Yeni Özellik Akışı (Feature Track)
```
[Orkestratör] ──► 1. SPEC_WRITER (Şartname & Lavish UI Prototipi)
                     │ (Kullanıcı tarayıcıda UI'ı onaylar)
                     ▼
                  2. SPEC_CRITIC (`brigade critique-spec` Danışman Denetimi)
                     │ (claude-opus-5-5-high / gemini-3.8-flash-high anti-borç analizi)
                     ▼
                  3. START-SLICE (`RED_TEST` Başlangıcı & İzole Worktree Kiralama)
                     │ (`brigade start-slice --name <slice> --track feature`)
                     ▼
                  4. SEAM_ARCHITECT (Kiralık Worktree'de Kırmızı Birim/Sözleşme Testi)
                     │ (`brigade advance` hakiki non-zero fail doğrulaması)
                     ▼
                  5. CODER (Worktree'de Kırmızı Testi Yeşile Çevirir)
                     │ (Test assertion'larını gevşetmesi yasaktır)
                     ▼
                  6. EXAMINER (Tek Geçişte Çift Eksenli Standart & Şartname İncelemesi)
                     ▼
                  7. QA_ENGINEER (Canlı Tarayıcı E2E Testi)
                     ▼
                  8. Deterministik Teslimat (`brigade finish-slice`)
                     (development birleştirme, şartname arşivleme, /edge-drift denetimi)
```

### 🧬 B. Refaktör Akışı (Structural Refactor Track)
```
[Orkestratör] ──► 1. SURGEON (Chef de Partie)
                     │ (Şişkin Controller'ları inceltir, Core domain reposunu soyutlar)
                     ▼
                  2. Karakterizasyon Testleri Doğrulaması (Sıfır Davranış Değişimi)
                     ▼
                  3. EXAMINER & Deterministik Teslimat (`brigade finish-slice`)
```

### 🐞 C. Hata Ayıklama Akışı (Bug-Fix Track)
```
[Orkestratör] ──► 1. RESEARCHER (AST ve Log Kök Neden Analizi - RCA)
                     ▼
                  2. SEAM_ARCHITECT (Hatayı Yeniden Üreten Karakterizasyon Testi)
                     ▼
                  3. CODER (Minimal ve Temiz Çözüm)
                     ▼
                  4. QA_ENGINEER (Regresyon Doğrulaması)
```

---

## 3. Antigraveyard & Otomatik Vardiya Değişimi

Geliştiricinin veya ajanın "bu ajanı kapatıp yenisini mi açayım?" diye düşünmesine gerek yoktur. Arka planda çalışan **`orchestrator_guard.py`** bunu matematiksel olarak yönetir:

* **İstasyon Hafızası (Reuse via `send_message`):**  
  Eğer ilgili rolde daha önce açılmış bir çalışan varsa, yeni bir alt-ajan türetilmez; görev doğrudan mevcut ajana `send_message` ile iletilir.
* **Fil ve Japon Balığı Bellek Modeli (Elephant vs. Goldfish):**
  * 🐘 **Kalıcı Fil İstasyonları (`PERSISTENT_ELEPHANT_ROLES`):** `SPEC_WRITER`, `RESEARCHER`, `SEAM_ARCHITECT`, `CODER`, `SURGEON`, `QA_ENGINEER` — alan bağlamını biriktirir ve YEŞİL bölgede (`< 45k` token) `send_message` ile sürekli yeniden kullanılır.
  * 🐟 **Kısa Ömürlü Japon Balığı İstasyonları (`EPHEMERAL_GOLDFISH_ROLES`):** `EXAMINER` ve `SPEC_CRITIC` — teyit yanlılığını (confirmation bias) engellemek için her inceleme/eleştiri turunda sıfır konuşma geçmişiyle taze (`invoke_subagent`) türetilir; guard YEŞİL bölgede dahi taze türetmeye izin verir ve önceki örneği `ROTATED` olarak işaretler.
* **Kota Koruma Politikası:**  
  Alt-ajan başlatılırken (`invoke_subagent`), insan kaptan aksini belirtmedikçe varsayılan olarak `Model: "flash"` kullanılır.
* **Bağlam Isısı Eşikleri (SSOT Thresholds):**
  * 🟢 **YEŞİL BÖLGE (< 45k token, `GREEN_HEAT_THRESHOLD = 45,000`):** Çalışan dinçtir, görev aynı ajana `send_message` ile iletilir.
  * 🟡 **SARI BÖLGE (45k - 75k token, `45,000 <= tokens < 75,000`):** Yeni bilet alımı durdurulur (`triage` dondurulur), aktif bilet tamamlanır.
  * 🔴 **KIRMIZI BÖLGE ($\ge 75k$ token, `YELLOW_HEAT_THRESHOLD = 75,000`):** Çalışan yorulmuştur (`EXHAUSTED`); rotasyon izni verilir veya acil durum kontrol noktası alınır.
* **Sıfır-Özet Devir (Zero-Handoff Invariant):**  
  Yorulan çalışan için pahalı ve hatalı "hafıza özeti" çıkarılmaz. Her iş paketi kendi dosya yolu ve test komutuyla bağımsız olduğu için, istasyon yeni ve soğuk (cold-start) bir çalışana temiz bir şekilde devreder.

---

## 4. UI Onay Kapısı (`lavish-axi`)

Kullanıcı arayüzüne dokunan tüm işlerde:
1. `SPEC_WRITER`, arayüzü doğrudan koda yazmadan önce `.lavish/<feature>.html` içerisinde etkileşimli bir prototip oluşturur.
2. `lavish-axi <file>` ile prototip ayağa kaldırılır.
3. **Kullanıcı Onayı Zorunludur:** Kullanıcı tarayıcıda prototipi inceleyip "Send & End" butonuna basmadan veya onayını vermeden `CODER` kesinlikle kod yazamaz.

---

## 5. TDD ve Test İntizamı (Test Immutability)

* `SEAM_ARCHITECT` tarafından yazılan kırmızı testler **değiştirilemez ve silinemez**.
* `CODER`, test dosyasını düzenleyemez. Sadece üretim kodunu yazarak testi yeşile çevirmekle yükümlüdür.
* Tüm testler WSL2 ortamında hermetik olarak koşulur (`npm test`, `vitest run`, `pytest`).

---

## 6. CLI Araçları ve Teşhis Komutları

Arka plandaki motorun durumunu elle denetlemek isterseniz aşağıdaki komutlar kullanılabilir:

```bash
# 1. İstasyonların ve Aktif Oturumların Durumu
wsl python3 tools/brigade/cli.py status <repo_path>
wsl python3 tools/brigade/cli.py stations <repo_path>

# 2. Kod Tabanı Sağlık & Derinlik Analizi (Audit)
wsl python3 tools/audit/cli.py <repo_path>

# 3. Teknik Borç & Değişim Frekansı Radarı (Radar)
wsl python3 tools/radar/cli.py <repo_path>

# 4. Kriz Kaydedici & Operasyonel Playbook Çıkarımı (Distill)
wsl python3 tools/distill/cli.py <repo_path>

# 5. Şartname Danışman Denetimi (Cross-Provider Spec Critic)
wsl python3 tools/brigade/cli.py critique-spec <repo_path> --spec <spec_path>

# 6. Yaşayan Alan Sözleşmeleri ve Sapma Denetimi (Drift)
wsl python3 tools/drift/cli.py check <repo_path>
```

---

## 7. Proje Standartları Belirleme (`coding_standards.md`)

Edge, projelerinize kafasına göre evrensel bir kod stili dayatmaz:
* Çalışılan projenin kök dizininde `coding_standards.md` aranır.
* Eğer yoksa, orkestratör sizi mülakata alarak (`/grill-me` veya `/grill-with-docs`) projenizin mimari tercihlerini (dil sürümleri, tip katılığı, klasör hiyerarşisi) kaydeder.
