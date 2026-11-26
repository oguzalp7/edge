# ▶️ Operational Playbook: Session-Pickup Protocol

Bu el kitapçığı, yeni bir oturum (sohbet penceresi veya CLI) başlatıldığında, önceki oturumun durumunu transkript okuma maliyeti ve bilişsel yorgunluk olmadan anında devralma (Cold-Start Zero-Amnesia) protokolünü yönetir.

---

## 🎯 1. Temel İlke (Zero-Transcript Rule)

> [!IMPORTANT]
> **Devasa Transkriptleri Asla Okuma!**  
> Yeni açılan bir oturumda geçmiş konuşma transkriptlerini (`transcript.jsonl`, `transcript_full.jsonl`) satır satır okumak, yüzbinlerce token tüketir ve bağlam penceresini henüz işe başlamadan çürütür (Session Amnesia).  
> Tek hakikat kaynağı `.edge/checkpoint.json` ve `brigade.json` durum dosyalarıdır.

---

## 🛡️ 2. Devralma Protokolü (Step-by-Step Pickup)

Yeni oturum başladığında ilk olarak aşağıdaki komut çalıştırılır:

```bash
python tools/brigade/cli.py resume <repo_path>
```

### Otomatik Gerçekleşen Operasyonlar:
1. **Kontrol Noktasının Tespiti:**
   * `.edge/checkpoint.json` okunur ve bilet bilgileri belleğe alınır.
2. **Git Dalı Eşitlemesi:**
   * Eğer kontrol noktasında aktif bir dal (`active_branch`) varsa, o dala geçilir (`git checkout`).
   * Eğer uncommitted WIP commit atılmışsa (`has_uncommitted_work == true`), en son `wip(checkpoint)` commit'i üzerinden devam edilir.
3. **FSM Belleğinin Restorasyonu:**
   * Durum makinesi duraklatılmadan önceki asıl duruma (`SURGERY`, `VERIFY`, `REVIEW`, vb.) geri döndürülür.
   * `checkpoint.json` arşive kaldırılır (`checkpoint.json.bak`).
4. **Eylem Vektörü Raporu:**
   * Devralan ajana veya kullanıcıya tam olarak hangi alt adımda kalındığı (`pending_substeps`) ve sıradaki eylemin ne olduğu (`next_action`) net bir prompt olarak sunulur.

---

## 📋 3. Operasyonel Kontrol Listesi (Operator Checklist)

Devralma sonrası ajan derhal şu adımları atar:

1. `brigade resume <repo>` çıktısını incele.
2. `next_action` yönergesini oku.
3. Eğer `SURGERY` durumunda kaldıysan:
   * Aktif Stack Profile'ın (`profiles/<id>/`) test komutunu çalıştır.
   * Gerekli cerrahi adımı tamamla.
   * `brigade advance` ile `VERIFY` aşamasına geç.
4. Eğer `GATE` veya `STAGING` durumunda kaldıysan:
   * İlgili kapıyı çalıştır ve doğrudan ilerle.
