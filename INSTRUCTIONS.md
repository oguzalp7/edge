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
                  2. SEAM_ARCHITECT (Kırmızı Birim/Sözleşme Testi)
                     │ (Başlangıçta patlayan test mühürlenir)
                     ▼
                  3. CODER (Kırmızı Testi Yeşile Çevirir)
                     │ (Test assertion'larını gevşetmesi yasaktır)
                     ▼
                  4. STANDARDS & SPEC EXAMINERS (Çift Eksenli İnceleme)
                     ▼
                  5. QA_ENGINEER (Canlı Tarayıcı E2E Testi)
                     ▼
                  6. EXPEDITER (Squash-Merge & no-mistakes ile PR)
```

### 🧬 B. Refaktör Akışı (Structural Refactor Track)
```
[Orkestratör] ──► 1. SURGEON (Chef de Partie)
                     │ (Şişkin Controller'ları inceltir, Core domain reposunu soyutlar)
                     ▼
                  2. Karakterizasyon Testleri Doğrulaması (Sıfır Davranış Değişimi)
                     ▼
                  3. STANDARDS EXAMINER & EXPEDITER
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
* **Bağlam Isısı Eşikleri:**
  * 🟢 **YEŞİL (< 180k token):** Çalışan dinçtir, görev aynı ajana verilir.
  * 🟡 / 🔴 **SARI / KIRMIZI ($\ge 180k$ token):** Çalışan yorulmuştur (`EXHAUSTED`).
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
```

---

## 7. Proje Standartları Belirleme (`coding_standards.md`)

Edge, projelerinize kafasına göre evrensel bir kod stili dayatmaz:
* Çalışılan projenin kök dizininde `coding_standards.md` aranır.
* Eğer yoksa, orkestratör sizi mülakata alarak (`/grill-me` veya `/grill-with-docs`) projenizin mimari tercihlerini (dil sürümleri, tip katılığı, klasör hiyerarşisi) kaydeder.
