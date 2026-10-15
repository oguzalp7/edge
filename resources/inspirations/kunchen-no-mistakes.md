# Kun Chen: no-mistakes (Local Git Proxy Gate)

- **Repo Linki:** [https://github.com/kunchenguid/no-mistakes](https://github.com/kunchenguid/no-mistakes)
- **Dokümantasyon:** [https://kunchenguid.github.io/no-mistakes/](https://kunchenguid.github.io/no-mistakes/)
- **Yazar:** Kun Chen (@kunchenguid)
- **Kategori:** Git Proxy / Deterministik Doğrulama Kapısı / Otomatik Kod İnceleme & Onarım

---

## 🎯 Projenin Temel Amacı ve Felsefesi

> *"Kill all the slop. Raise clean PR."* (Tüm yapay zeka çöpünü yok et. Tertemiz PR aç.)

`no-mistakes`, geliştiricinin veya ajanın `origin` yerine yerel bir git proxy'sine (`git push no-mistakes`) kod göndermesini sağlayan bağımsız bir denetim motorudur.

Geliştiricinin çalışma ortamını bozmadan arka planda tek kullanımlık bir git worktree açar; sırasıyla **rebase $\rightarrow$ lint $\rightarrow$ test $\rightarrow$ review $\rightarrow$ document $\rightarrow$ push $\rightarrow$ PR $\rightarrow$ CI** hattını koşturur ve sadece her şey yeşil olduğunda gerçek hedefe kodu basar.

---

## ⚙️ Nasıl Çalışır? (Arka Plandaki Mimari Mekanizma)

1. **Bare Repository & Git Hook:**
   - `no-mistakes init` çalıştırıldığında yerel makinede (örn. `~/.no-mistakes/repos/<hash>.git`) bir bare git deposu açar ve projenize `no-mistakes` adında bir git remote ekler.
   - Buraya push atıldığında `post-receive` hook tetiklenir veya komut satırından `no-mistakes axi run` ile doğrudan sürülür.
2. **İzole Tek Kullanımlık Worktree:**
   - Kodunuz ana dizinde kalır; proxy arka planda `~/.no-mistakes/worktrees/` altına temiz bir kopyasını açar.
3. **Deterministik Adım Hattı:**
   - `rebase`: Hedef dal ile temiz rebase kontrolü.
   - `lint`: Tanımlı linter komutunu koşturur (varsa auto-fix dener).
   - `test`: Test komutunu koşturur, hata çıkarsa ajan test izini alıp tamir eder.
   - `review`: Yapılandırılan LLM ajanını (`antigravity`, `claude`, `codex`, `pi` vb.) diff, commit geçmişi ve PRD/spec dosyalarıyla besler. Ajan kod incelemesini yapar; bulgular onay kapısına (approval gate) veya otomatik onarıma gider.
   - `document`: Yapılan değişikliğe göre ilgili dokümanları ve CHANGELOG'u günceller.
   - `push & PR`: Tüm adımlar kusursuz biterse dalı GitHub'a basıp özet PR açar.

---

## 📝 Yönergeler ve Sistem Promptları Eklenebilir mi?

**KESİNLİKLE EVET!** Proje kök dizinindeki `.no-mistakes.yaml` dosyası üzerinden her adıma özel kurallar ve komutlar tanımlanabilir:

```yaml
# .no-mistakes.yaml (Proje Kök Dizininde)

commands:
  prepare: "npm install"
  lint: "npm run lint"
  test: "npm test"
  format: "npm run format"

# Ajanın asla değiştirmemesi gereken korunan dosyalar
protected_paths:
  - "package.json"
  - "pnpm-lock.yaml"
  - "migrations/**"

# İnceleme ve Test Adımlarına Özel Prompt Yönergeleri
review:
  path_instructions:
    - path: "src/core/**"
      instructions: "Check for strict single responsibility. Reject functions with cyclomatic complexity > 10. Ensure zero external I/O leaks."
    - path: "src/api/**"
      instructions: "Verify all endpoints validate input schemas with Zod and sanitize responses."

test:
  instructions: "Ensure no tautological mock tests are added. Tests must assert actual runtime behaviors and error states."

document:
  instructions: "Update internal docs only if public API contracts changed."

# Otomatik onarım sınırları (0 = sadece raporla, dokunma)
auto_fix:
  lint: 1
  test: 2
  review: 0 # Güvenlik için inceleme bulgularını insana sor
```

### `--intent` Parametresinin Hayati Rolü
`no-mistakes axi run --intent "<amaç>"` çalıştırıldığında, ajana "neyin yapılmak istendiği" (authoritative intent) verilir. Bu sayede inceleme ve test ajanları sırf testi geçirmek için özellikleri sessizce silemez veya kapsam dışı değişiklikler yapamaz.

---

## 🚀 Bizim `edge` Pluginimiz İçin Çıkarımlar

- `no-mistakes`, Antigravity içinde `hooks.json` ile entegre edilebilecek en güçlü harici denetim hattıdır.
- Kod tabanında satır sayısı ve dosya karmaşıklığı arttığında, `review.path_instructions` ve `test.instructions` ile ajanlara katı mimari kısıtlar (örneğin dosya satır limiti, fonksiyon karmaşıklık limiti) koymak mümkündür.
