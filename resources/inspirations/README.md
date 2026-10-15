# 💡 Inspirations (İlham Kaynakları ve Duayen İncelemeleri)

Bu dizin, `edge` plugininin mimarisini kurgularken dünyadaki en iyi agentic engineering pratiklerini ve bu alandaki öncü mühendislerin repolarını sentezlemek amacıyla oluşturulmuştur.

| Dosya Adı | Yazar / Proje | Odak / Ana Felsefe | Bağlantı |
|---|---|---|---|
| [mattpocock-skills.md](mattpocock-skills.md) | **Matt Pocock** (`skills`) | Real Engineering > Vibe Coding, Grilling, Ubiquitous Language, 2-Eksenli Code Review | [GitHub](https://github.com/mattpocock/skills) |
| [kunchen-no-mistakes.md](kunchen-no-mistakes.md) | **Kun Chen** (`no-mistakes`) | "Kill all the slop", Git Proxy Gatekeeper, Deterministik Lint/Test/Review/CI Pipeline | [GitHub](https://github.com/kunchenguid/no-mistakes) |
| [kunchen-tasks-axi.md](kunchen-tasks-axi.md) | **Kun Chen** (`tasks-axi`) | AXI (Agent eXperience Interface), Sıfır Output Tokenli Backlog, Ready Sorguları | [GitHub](https://github.com/kunchenguid/tasks-axi) |
| [poteto-pstack.md](poteto-pstack.md) | **Poteto (Lauren Tan)** (`pstack`) | Fearless Parallelism, "Daha az ama öz kod", 23 Playbook, Çalışma Zamanı Doğrulaması | [GitHub](https://github.com/cursor/plugins/tree/main/pstack) |
| [dexhorthy-12-factor-agents.md](dexhorthy-12-factor-agents.md) | **Dex Horthy** (`12-factor-agents`) | Context Engineering, Deterministik Akış, Küçük Odaklı Ajanlar, Stateless Reducer | [GitHub](https://github.com/humanlayer/12-factor-agents) |

---

## 🧭 Ortak Çıkarım: "Ajan ve İnsan Dostu Bir Kod Tabanı"

Tüm bu kaynakların birleştiği en kritik ortak payda:
> **"Bir kod tabanı insan için ne kadar karmaşık ve aşırı kalabalıksa, yapay zeka ajanı için de o kadar tehlikelidir."**

1. Binlerce satırlık monolitik dosyalar context penceresini tüketir ve dikkati dağıtır (*Dex Factor 3*).
2. Dosya sayısı değil; **dosya başına düşen satır sayısı ve sorumluluk miktarı** kodun ölüm fermanıdır (*Uncle Bob SRP & Clean Code*).
3. Büyük dosyalar yerine; küçük, derin arayüzlü (deep modules), kendi testleriyle izole edilmiş modüller hem insanın kaybolmasını önler hem de ajanın tek seferde tam isabetle kod değiştirmesini sağlar (*Ousterhout & Matt Pocock*).
