# Matt Pocock: Skills For Real Engineers

- **Repo Linki:** [https://github.com/mattpocock/skills](https://github.com/mattpocock/skills)
- **Yazar:** Matt Pocock (@mattpocock)
- **Kategori:** Agent Skills / Prosedürel Mühendislik / Tasarım ve Uyumlandırma

---

## 🎯 Projenin Temel Amacı ve Felsefesi

Matt Pocock'un geliştirdiği `skills` kütüphanesi, yapay zeka ile "vibe coding" yapmak yerine **gerçek mühendislik (real engineering)** disiplinini sürdürmek için tasarlanmıştır.

Birçok framework (GSD, BMAD, Spec-Kit gibi) bütün geliştirme sürecini sahiplenip geliştiricinin elinden kontrolü alır. Bu kütüphanenin felsefesi tam tersidir:
- **Küçük, birleştirilebilir (composable) ve uyarlanabilir** yetenekler.
- Her LLM modeliyle çalışabilme.
- Sürecin ve kararların kontrolünü geliştiricide tutma.

---

## 💡 Öne Çıkan Temel Fikirler ve Çözümler

### 1. "Ajan Benim İstediğimi Yapmadı" Problemi (Uyumsuzluk / Misalignment)
- **Sorun:** Yazılım geliştirmedeki en yaygın hata kurgusal uyumsuzluktur. Ajanın ne yapacağını anladığını sanırsınız ama bambaşka bir şey üretir.
- **Çözüm: `/grill-me` ve `/grill-with-docs` (Grilling Sessions)**
  - Kod yazılmadan önce ajanı bir **hasmane mülakatçıya (adversarial interviewer)** dönüştürür.
  - Ajan size detaylı ve derinlemesine sorular sorarak gereksinimlerdeki boşlukları, sınır durumları ve riskleri kodlamaya başlamadan önce açığa çıkarır.

### 2. "Ajan Çok Fazla Konuşuyor ve Jargon Uyduruyor" Problemi
- **Sorun:** Projeye yeni giren bir ajan bağlamı anlamadığı için 1 kelimelik yere 20 kelime yazar, domain terminolojisini karıştırır.
- **Çözüm: Ortak Dil (Ubiquitous Language) ve ADR'ler**
  - Proje kavramlarını netleştiren terimler sözlüğü (`ubiquitous-language`) ve mimari karar kayıtları (`ADR`).
  - Değişken, fonksiyon ve dosya adları domain modeliyle tam örtüşür. Kodun içindeki gereksiz dolaylı açıklamalar ortadan kalkar.

### 3. İki Eksenli Kod İncelemesi: `/code-review`
- Kod değişikliklerini iki bağımsız eksende inceler:
  - **Spec-Wise (Gereksinim / Şartname Uyumu):** Kod, PRD'de veya issue'da istenen işi gerçekten yaptı mı? Kapsam kayması (scope creep) var mı?
  - **Standards-Wise (Standartlar & Zanaat):** Kod projenin mimari kurallarına, tip güvenliğine ve test standartlarına uyuyor mu?

### 4. Aşamalı Dönüşüm Hunisi
- `/grilling` $\rightarrow$ `/to-spec` (sınırlar, dikişler ve kontratlar) $\rightarrow$ `/to-tickets` (küçük, dikey, doğrulanabilir dilimler) $\rightarrow$ `/tdd` (test-öncelikli geliştirme).

---

## 🚀 Bizim `edge` Pluginimiz İçin Çıkarımlar

1. **İnsan Kontrolü (Prosedürler > Rastgele Yetenekler):** Ajanın ne zaman ne yapacağını tahmin etmeye çalışmak yerine, geliştiricinin bilinçli tetiklediği net adımlar (`/edge-grill`, `/edge-review`) kurmalıyız.
2. **Kodu Yazmadan Önce Sıkıştırma:** Kod tabanındaki satır sayısını ve dağınıklığı azaltmanın ilk yolu, gereksinimi kodlamadan önce sözlük ve domain modeline oturtmaktır.
