# Dex Horthy: 12-Factor Agents (Principles for Building Reliable LLM Applications)

- **Repo Linki:** [https://github.com/humanlayer/12-factor-agents](https://github.com/humanlayer/12-factor-agents)
- **Yazar:** Dexter Horthy (@dexhorthy - HumanLayer Kurucusu & CEO)
- **Kategori:** Context Engineering / Ajan Mimarisi / Üretim Kalitesinde Yazılım İlkeleri

---

## 🎯 Projenin Temel Amacı ve Felsefesi

Heroku'nun ünlü *12-Factor App* manifestosundan esinlenen bu proje, üretim ortamında (production) müşterilerin önüne konulabilecek kalitede güvenilir yapay zeka sistemleri inşa etmenin mühendislik ilkelerini ortaya koyar.

> *"İyi yapay zeka ajanları 'al sana prompt, al sana araçlar, hedefe ulaşana kadar dön' kalıbını takip etmez. Ajanlar çoğunlukla deterministik yazılımlardır; yapay zeka sadece doğru noktalara serpiştirilmiş stratejik karar adımlarıdır."*

---

## 💡 12 Temel İlke (The 12 Factors)

1. **Factor 1: Doğal Dilden Araç Çağrısına (Natural Language to Tool Calls):** LLM'ler nihai yürütücü değil, karar vericidir; çıktılar araç çağrılarına dönüştürülmelidir.
2. **Factor 2: Promptlarının Sahibi Ol (Own Your Prompts):** Büyük framework soyutlamalarına (LangChain vb.) güvenmek yerine promptların üzerinde doğrudan kontrol sahibi ol.
3. **Factor 3: Bağlam Pencerenin Sahibi Ol (Own Your Context Window - Context Engineering):** LLM'in dikkatine ne giriyorsa özenle kürate et. Gereksiz token yükü ajanın zekasını köreltir.
4. **Factor 4: Araçlar Yalnızca Yapılandırılmış Çıktılardır (Tools Are Just Structured Outputs):** Tool calling mekanizmasını JSON şemalarıyla tip güvenli veri üretimi için kullan.
5. **Factor 5: Yürütme Durumu ile İş Durumunu Birleştir (Unify Execution & Business State):** Ajanın nerede kaldığı ile sistemin durumu ayrı dünyalar olmamalıdır.
6. **Factor 6: Basit API'lerle Başlat/Duraklat/Devam Et (Launch/Pause/Resume):** İnsan onayı ve müdahalesi için duraklatma noktaları ilk sınıf vatandaş olmalıdır.
7. **Factor 7: İnsanla Araç Çağrılarıyla İletişim Kur (Contact Humans with Tool Calls):** İnsana soru sormak da bir tool çağrısıdır (`ask_question`).
8. **Factor 8: Kendi Akış Kontrolünün Sahibi Ol (Own Your Control Flow):** Döngüleri ve state machine'i modele devretme, deterministik kod ile yönet.
9. **Factor 9: Hataları Bağlam Penceresine Sıkıştır (Compact Errors into Context Window):** 500 satırlık stack trace yerine hatanın özünü ajana besle.
10. **Factor 10: Küçük ve Odaklı Ajanlar (Small, Focused Agents):** Her şeyi yapan devasa ajanlar yerine, dar sorumlulukları olan mikro ajanlar kullan.
11. **Factor 11: Her Yerden Tetikle (Trigger from Anywhere):** Ajan webhook'tan, CLI'dan veya etkinlikten beslenebilmelidir.
12. **Factor 12: Ajanı Durumsuz Bir İndirgeyici Yap (Stateless Reducer):** Ajan `(Current State, Action) -> New State` fonksiyonu gibi saf bir reducer olarak tasarlanmalıdır.

---

## 🚀 Bizim `edge` Pluginimiz İçin Çıkarımlar

1. **Context Engineering:** Kod tabanındaki dosyaların satır sayısı çok yüksek olduğunda, Factor 3 ("Own Your Context Window") ihlal edilmiş olur. Ajanın önüne 3.000 satırlık dev bir dosya koyduğunuzda, dikkati dağılır ve hata yapma olasılığı katlanır.
2. **Program Tasarımı (Call Stack & Tipler):** Koda girmeden önce fonksiyon imzalarını ve çağrı yığınını belirlemek, token maliyetini minimize ederken kesinliği maksimuma çıkarır.
