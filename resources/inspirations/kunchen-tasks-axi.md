# Kun Chen: tasks-axi (Agent eXperience Interface for Task Management)

- **Repo Linki:** [https://github.com/kunchenguid/tasks-axi](https://github.com/kunchenguid/tasks-axi)
- **AXI Şartnamesi:** [https://axi.md/](https://axi.md/)
- **Yazar:** Kun Chen (@kunchenguid)
- **Kategori:** Backlog Yönetimi / Ajan Ergonomisi (AXI) / Düşük Tokenli Görev Takibi

---

## 🎯 Projenin Temel Amacı ve Felsefesi

Yapay zeka ajanlarıyla çalışırken en büyük problemlerden biri görev listelerini yönetmektir:
- Ajan her görev eklediğinde veya durum güncellediğinde koca bir `TODO.md` dosyasını baştan üretir (on binlerce pahalı output token harcar).
- Baştan yazma sırasında görevler kaybolur, sıra bozulur veya ajanın dikkati dağılır.

**`tasks-axi`'nin Çözümü:**
Ajanlar için tasarlanmış ergonomik CLI (AXI - Agent eXperience Interface). 
- İnsan tarafından okunabilir `backlog.md` dosyasını yerinde (in-place) değiştirir.
- Değişiklikler tek bir kısa komutla (`tasks-axi add ...`, `tasks-axi done ...`) yapılır; ajanın çıktı token maliyeti neredeyse **sıfırdır**.
- Çıktılar insan için süslü tablolar yerine, ajanlar için sıkıştırılmış, yapılandırılmış **TOON** formatında verilir.

---

## 💡 Öne Çıkan Temel Özellikler

1. **Bağımlılık Grafiği ve Ready Sorgusu (`tasks-axi ready`):**
   - Görevler birbirine bağlanabilir (`--blocked-by <id>`).
   - Ajan `tasks-axi ready` dediğinde yalnızca engeli kalkmış, hemen başlanabilecek iş paketlerini görür. Arka arkaya çalışan alt ajanlar birbirini ezmez.
2. **Kısa Gövde, Derin Detay Ayrımı:**
   - Liste görünümünde sadece ID ve başlık döner (token tasarrufu).
   - Ajan göreve başlamadan önce `tasks-axi show <id> --full` diyerek tüm şartnameyi ve kabul kriterlerini tek seferde okur.
3. **Session Hook Desteği:**
   - Her oturum başlangıcında (`SessionStart`) güncel hazır işleri otomatik olarak ajanın bağlamına minimal tokenla sunar.

---

## 🧭 `frontier-axi` ve `tasks-axi` Kardeşliği (Bizim Eski Deneyimimizle Bağı)

Kullanıcımızın önceki tecrübesinde oluşturduğu `frontier-axi` kuralı bu felsefenin mükemmel bir uzantısıdır:
- **`frontier-axi` (Bilişsel Sis ve Karar Aşaması):** Fikir henüz olgunlaşmamışken, mimari arayüzler ve alternatifler tartışılırken kullanılır. Kod yazılmaz.
- **`tasks-axi` (Deterministik İcra Aşaması):** Kararlar verilmiş, kabul kriterleri netleşmiş ve dikey dilimler ayrılmış iş paketleridir. 

> **Altın Kural:** Kabul kriteri ve dikey sınırları netleşmemiş hiçbir fikir doğrudan `tasks-axi`'ye yazılamaz!

---

## 🚀 Bizim `edge` Pluginimiz İçin Çıkarımlar

- Görev yönetimi için ajana serbest metin `TODO.md` yazdırmamalıyız; deterministik, token tasarruflu bir CLI yapısı (veya `tasks-axi`) kullanmalıyız.
- Kod tabanındaki kalabalık satırları ayıklarken yapacağımız refactor görevlerini bağımlılık sırasına göre dizebilmeliyiz.
