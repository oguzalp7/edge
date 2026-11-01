# ⏸️ Operational Playbook: Pause-Safely Protocol

Bu el kitapçığı, bağlam penceresi doygunluğa ulaştığında veya kullanıcı çalışmayı duraklatmak istediğinde, devam eden işleri sıfır bağlam kaybıyla dondurma ve dayanıklı bir kontrol noktası (`.edge/checkpoint.json`) oluşturma protokolünü yönetir.

---

## 🎯 1. Tetiklenme Koşulları (Trigger Matrix)

1. **Bağlam Isı Seviyesi (SSOT Context Heat Zones):**
   * **🟢 YEŞİL BÖLGE (< 45k token, `GREEN_HEAT_THRESHOLD = 45,000`):** Normal operasyon. Kalıcı istasyonlar korunur ve `send_message` ile yeniden kullanılır.
   * **🟡 SARI BÖLGE (45k - 75k token, `45,000 <= tokens < 75,000`):** Yeni bilet alımı durdurulur (`triage` dondurulur). Aktif bilet bitirilir (Gate ve Staging tamamlanır). Bilet merge edildikten hemen sonra otomatik olarak `brigade pause` tetiklenir.
   * **🔴 KIRMIZI BÖLGE (>= 75k token, `YELLOW_HEAT_THRESHOLD = 75,000`):** Acil durum kontrol noktası (Emergency Checkpoint). Aktif cerrahi/doğrulama anında dahi olsa bekletilmeden `brigade pause` çalıştırılır. Kirli dosyalar `wip(checkpoint)` commit'i ile güvenceye alınır.

2. **Kullanıcı Talebi (Human Pause):**
   * Kullanıcı *"dur"*, *"mola verelim"*, *"yarın devam ederiz"*, *"oturum aç/kapat yapalım"* dediğinde.

---

## 🛡️ 2. Yürütme Protokolü (Execution Steps)

Ajan veya operatör aşağıdaki komutu hedeflenen repo üzerinde çalıştırır:

```bash
python tools/brigade/cli.py pause <repo_path> --reason <REASON>
```

Örnek nedenler:
* `--reason CONTEXT_LIMIT_YELLOW`
* `--reason CONTEXT_LIMIT_RED`
* `--reason HUMAN_PAUSE`

### Otomatik Gerçekleşen Operasyonlar:
1. **Kirli Ağaç Tespiti & Güvenli Commit:**
   * `git status --porcelain` kontrol edilir.
   * Eğer kaydedilmemiş değişiklikler varsa, `wip(checkpoint): safe pause at <STATE> [<TICKET_ID>]` commit'i atılır. Çalışma ağacı temiz bırakılır; hiçbir kod kaybı yaşanmaz.
2. **Durum Dayanıklılığı (`.edge/checkpoint.json`):**
   * Aktif bilet, domain, dosya, kural, tamamlanan ve bekleyen alt adımlar ile sonraki eylem vektörü JSON kontrol noktasına yazılır.
3. **FSM Geçişi:**
   * Durum makinesi `CycleState.PAUSED` durumuna geçer.
4. **Devir Özeti:**
   * Yeni oturumun nasıl başlayacağını belirten tek satırlık devir yönergesi ekrana basılır.

---

## 🚫 3. Negatif Kısıtlar (Anti-Patterns)

* ❌ **Kirli Ağacı Terk Etme:** Asla `git stash` veya uncommitted dosyalar bırakarak oturumu sonlandırma.
* ❌ **FSM'i Askıda Bırakma:** Kontrol noktası oluşturmadan oturumu bitirip yeni ajanı "ne yapıyorduk?" tahminine zorlama.
* ❌ **Devasa Transcript Okuma:** Bir sonraki ajanın geçmiş transkriptleri okumasını öğütleme; kontrol noktası tek hakikat kaynağıdır.
