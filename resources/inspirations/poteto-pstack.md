# Poteto (Lauren Tan): pstack (Fearless Parallelism & Rigorous Engineering)

- **Repo Linki:** [https://github.com/cursor/plugins/tree/main/pstack](https://github.com/cursor/plugins/tree/main/pstack)
- **Yazar:** Lauren Tan (@poteto - Eski Meta React Core Team, Netflix, SpaceX, Cursor)
- **Kategori:** Rigorous Agent Workflows / Doğrulama Döngüleri / Stacked PRs / Zanaat

---

## 🎯 Projenin Temel Amacı ve Felsefesi

> *"Yapay zeka çok fazla çöp kod (slop) yazıyor. Buna katılıyorum. Yirmi kişilik bir çöp üretici ordusu gibi kod yayınlamak istemiyorum. Kalitesiz hız bir amaç değildir. Eğer hızlı gitmek istiyorsan, önce derine in."*

`pstack`, Cursor/SpaceX ortamında binlerce yüksek kaliteli PR açabilmek için geliştirilmiş bir mühendislik protokolüdür:
- Amaç satır sayısını (LOC) artırmak değil; tam aksine **daha az ama daha yüksek kaliteli kod yazmaktır**.
- **Korkusuz Paralellik (Fearless Parallelism):** Eğer tek bir ajanın doğru, doğrulanabilir kod yazdığına güvenebiliyorsanız, o zaman birden fazla ajanı güvenle paralel koşturabilirsiniz.
- **Model Çeşitliliği:** Her göreve uygun model (derin akıl yürütme ve mimari için Opus/Gemini Thinking; kod üretimi ve mekanik refactor için hızlı modeller).

---

## 💡 Öne Çıkan Temel Özellikler

### 1. 23 Uzman Oyun Kitabı (Playbooks - `/poteto-mode`)
Geliştirici sadece isteğini söyler, sistem göreve göre hazır bir rehberi devreye sokar:
- **`investigation`:** Salt okunur inceleme (sistem nasıl çalışıyor, neden böyle yapıldı?).
- **`bug-fix`:** Önce hatayı yeniden üret (repro), kök nedeni bul, çalışma zamanı kanıtıyla düzelt.
- **`perf` / `hillclimb`:** Bir metriğe (bellek, gecikme, CPU) karşı hipotez kurup, her kazanımda bir commit atarak adım adım iyileştirme.
- **`refactoring`:** Davranışı koruyan yapısal ve biçimsel değişiklik.
- **`runtime-forensics` & `trace-forensics`:** CPU profili, heap snapshot ve flame graph incelemeleri.
- **`opening-a-pr`:** Küçük sıralı commit'lerden, konvansiyonel başlık ve özet brifingle PR açma.

### 2. Doğrulama (Verification) Her Şeyin Merkezindedir
- Ajan sadece kod yazıp bırakmaz; yazdığı kodun çalıştığını kanıtlamak için testleri çalıştırır, ekran görüntüleri/loglar alır.
- Geliştirici ajan ile tarayıcı/terminal arasında bir "et proxy'si" (meat proxy) olmaktan çıkarılır.

### 3. Stacked PRs (Yığılmış Küçük Çekme İstekleri)
- Büyük ve okunamaz monolitik PR'lar yerine; birbirinin üzerine binen, küçük, atomik, bağımsız doğrulanmış dallar.

---

## 🚀 Bizim `edge` Pluginimiz İçin Çıkarımlar

1. **Satır Sayısını Azaltma Felsefesi:** Kullanıcımızın "kod düzenli ama satır sayısı çok kalabalık" tespitine en iyi yanıt `pstack`'in *"write less, but higher quality code"* ilkesidir.
2. **Spesifik Refactor & Forensic Playbook'ları:** Şişkin dosyaları parçalara ayırırken gerileme (regression) olmaması için davranış korumalı refactor protokolleri işletilmelidir.
