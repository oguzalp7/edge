#!/usr/bin/env python3
"""
Playbook Generator for edge-distill.
Renders evidence-based operational playbooks into GitHub Flavored Markdown
under rules/playbooks/generated/<domain>-playbook.md.
"""

from pathlib import Path
from typing import Optional, Union
from datetime import datetime

from tools.distill.models import DistillReport, PlaybookProposal


class PlaybookGenerator:
    """
    Renders distilled intelligence into strict, evidence-based operational playbooks
    and emerging domain proposals.
    """

    def __init__(self, repo_path: Union[str, Path]):
        self.repo_path = Path(repo_path)
        self.default_output_dir = self.repo_path / "rules" / "playbooks" / "generated"
        self.proposals_dir = self.repo_path / "rules" / "playbooks" / "proposals"

    def generate(self, report: DistillReport, output_path: Optional[Union[str, Path]] = None) -> Path:
        """
        Generates markdown content from DistillReport and writes to disk.
        Returns the absolute Path of the created file.
        """
        if output_path:
            target_file = Path(output_path)
        else:
            self.default_output_dir.mkdir(parents=True, exist_ok=True)
            target_file = self.default_output_dir / f"{report.domain.lower()}-playbook.md"

        target_file.parent.mkdir(parents=True, exist_ok=True)

        content = self.render_markdown(report)
        target_file.write_text(content, encoding="utf-8")
        report.playbook_path = str(target_file)
        return target_file

    def render_markdown(self, report: DistillReport) -> str:
        """Renders GitHub Flavored Markdown matching Edge Plugin standards."""
        domain_title = report.domain.capitalize()
        scaffolded_str = ", ".join(f"`{s}`" for s in report.scaffolded_files) if report.scaffolded_files else f"`src/lib/{report.domain}/repository.ts`"
        test_cmd = (
            report.test_seams[0].get("command")
            if report.test_seams and "command" in report.test_seams[0]
            else f"npm run test:unit -- {report.domain}"
        )

        md = []

        # Header
        md.append(f"# 📖 Operational Playbook: {domain_title} Domain Architecture & Refactoring Recipes\n")
        md.append("> [!NOTE]")
        md.append(f"> Bu operasyonel el kitapçığı, `edge-distill` motoru tarafından **{domain_title}** domaini üzerindeki gerçek cerrahi adımlardan, derleyici loglarından, FSM durum geçişlerinden ve git mikro-commit'lerinden otomatik olarak damıtılmıştır (distilled).\n")
        md.append("---\n")

        # 1. Domain Profile & Context Table
        md.append("## 🧭 1. Domain Profili ve Veri İzi Bağlamı (Data Trail Context)\n")
        md.append("| Metrik / Parametre | Değer |")
        md.append("| :--- | :--- |")
        md.append(f"| **Hedef Domain** | `{report.domain}` |")
        md.append(f"| **İz / Hat (Track)** | `{report.track.upper()}` |")
        md.append(f"| **Hedef Kontrolör** | `{report.target_file}` |")
        md.append(f"| **Modüler Depo (Repository)** | {scaffolded_str} |")
        md.append(f"| **Temel Dal (Base Branch)** | `{report.base_branch}` |")
        md.append(f"| **Aktif Dal (Active Branch)** | `{report.active_branch or 'N/A'}` |")
        md.append(f"| **Kaynak Bilet ID** | `{report.ticket_id or 'N/A'}` |")
        md.append(f"| **Damıtılma Zamanı** | `{report.created_at}` |\n")
        md.append("---\n")

        # 2. Negative Constraints Ledger
        md.append("## 🚫 2. Negatif Kısıtlar Kütüğü (Negative Constraints Ledger)\n")
        md.append("> [!CAUTION]")
        md.append("> **Sıfır Toleranslı Mimari İhlaller:**")
        md.append("> Aşağıdaki anti-pattern'ler doğrudan `tools/gate.py` veya derleyici tarafından engellenir. Bu kural ve kısıtları ihlal eden cerrahi adımlar derhal geri alınır (rollback).\n")

        if report.negative_constraints:
            for nc in report.negative_constraints:
                sev_badge = "🔴 [KRİTİK]" if nc.severity == "CRITICAL" else "🟡 [UYARI]"
                md.append(f"### {sev_badge} {nc.title}")
                md.append(f"* **Anti-Pattern:** {nc.anti_pattern}")
                md.append(f"* **Risk / Neden Yasak:** {nc.risk}")
                md.append(f"* **Zorunlu Reçete (Required Pattern):** {nc.required_pattern}")
                md.append(f"* **Kural Kodu:** `{nc.rule_id}` (Kaynak: `{nc.source}`)\n")
        else:
            md.append("Kayıtlı negatif kısıt bulunmamaktadır.\n")

        md.append("---\n")

        # 3. AST / Code Diff Pattern
        md.append("## 🔄 3. Yapısal Dönüşüm Şablonu (AST & Code Diff Pattern)\n")
        md.append("> [!IMPORTANT]")
        md.append(f"> **Daralma İlkesi (Contraction Invariant):** `{report.target_file}` dosyası kesinlikle daralmalıdır ($\\Delta\\text{{SLOC}} < 0$). Veritabanı sorguları ve mutasyonları tamamen domain repository katmanına izole edilmelidir.\n")

        if report.diff_patterns:
            dp = report.diff_patterns[0]
            md.append(f"**Açıklama:** {dp.description}\n")
            if dp.target_delta != 0 or dp.net_lines != 0:
                md.append(f"* **Kontrolör SLOC Değişimi:** `{dp.target_delta:+d}` satır")
                md.append(f"* **Global Net SLOC:** `{dp.net_lines:+d}` satır\n")

            md.append("### ❌ ÖNCE (BEFORE): Monolitik Kontrolör & SQL Sızıntısı")
            md.append("```typescript")
            md.append(dp.before_code)
            md.append("```\n")

            md.append("### ✅ SONRA (AFTER): İnce Kontrolör & Atomik Domain Repository")
            md.append("```typescript")
            md.append(dp.after_code)
            md.append("```\n")

        md.append("---\n")

        # 4. Rescue Loops & Prescriptions
        md.append("## 🛟 4. Kurtarma Döngüleri ve İyileştirme Reçeteleri (Rescue Loops)\n")
        md.append("> [!TIP]")
        md.append("> **Kanıtlanmış Deterministik Çözümler:**")
        md.append("> Ajanlar kapılarda takıldığında veya derleyici hataları aldığında rastgele deneme-yanılma yapmak yerine aşağıdaki deterministik reçeteleri uygular.\n")

        if report.rescue_loops:
            for rl in report.rescue_loops:
                md.append(f"### 🛠️ [{rl.stage}] {rl.rule_enforced}")
                md.append(f"* **Hata Semptomu (Symptom):** {rl.symptom}")
                md.append(f"* **Kök Neden (Root Cause):** {rl.root_cause}")
                md.append(f"* **Deterministik Müdahale (Rescue Move):** {rl.remediation}")
                md.append("* **Doğrulama Komutu (Verification Command):**")
                md.append(f"  ```bash\n  {rl.verification_cmd}\n  ```\n")
        else:
            md.append("Kayıtlı kurtarma döngüsü bulunmamaktadır.\n")

        md.append("---\n")

        # 5. Hermetik Doğrulama ve Test Seam Reçetesi
        md.append("## 🧪 5. Hermetik Doğrulama ve Test Seam Reçetesi\n")
        md.append(f"Bu domain için belirlenmiş birim test dikişi: `{test_cmd}`\n")
        if report.compiler_fixes:
            md.append("### 🔧 Yakalanan ve Çözülen Derleyici Hataları (TypeScript Fixes):")
            for cf in report.compiler_fixes:
                code_str = cf.get("code", "TS")
                desc = cf.get("description", "")
                md.append(f"- **`{code_str}`**: {desc}")
            md.append("")

        md.append("---\n")

        # 6. Verification Checklist
        md.append("## ✅ 6. Operasyonel Kontrol Listesi (Deterministic Verification Matrix)\n")
        md.append(f"- [ ] **MigrationGate Invariant:** `src/db/schema/*` ve `drizzle/` dizinlerine kesinlikle dokunulmadı (0 şema değişikliği).")
        md.append(f"- [ ] **Hedef Kapsam Daralması:** `{report.target_file}` dosyası kesinlikle daraldı ($\\Delta\\text{{SLOC}} < 0$).")
        md.append(f"- [ ] **Scaffolding Bütçesi:** Eklenen repository satırları tanımlı toleransı aşmadı.")
        md.append(f"- [ ] **Veritabanı İzolasyonu:** Kontrolörde ham `db.select`, `db.insert`, `db.update`, `db.delete` çağrısı kalmadı.")
        md.append(f"- [ ] **ACID & Atomiklik:** Çoklu tablo mutasyonları `db.transaction()` bloğu içinde güvene alındı.")
        md.append(f"- [ ] **Tip Bütünlüğü:** `[key: string]: any;` veya `as any` tip kaçamağı içermez; Drizzle şema tipleri korundu.")
        md.append(f"- [ ] **Karakterizasyon Testleri:** `{test_cmd}` testi 100% yeşil geçti.")
        md.append(f"- [ ] **TypeScript Temizliği:** `npx tsc --noEmit` hatasız (0 error) sonuç verdi.")
        md.append(f"- [ ] **Verification Gate:** `python tools/gate.py` sıfır hatayla geçti.\n")

        md.append("### 💻 Deterministik Doğrulama Komutları (Terminal One-Liners)\n")
        md.append("```bash")
        md.append(f"# 1. Şema ve dosya izolasyonunu doğrula (MigrationGate)")
        md.append(f"git diff --name-only {report.base_branch}...HEAD\n")
        md.append(f"# 2. SLOC daralmasını ve bütçeyi doğrula (Target Contraction)")
        md.append(f"git diff --numstat {report.base_branch}...HEAD\n")
        md.append(f"# 3. TypeScript tip kontrolünü çalıştır")
        md.append(f"npx tsc --noEmit\n")
        md.append(f"# 4. Karakterizasyon test seam'ini çalıştır")
        md.append(f"{test_cmd}\n")
        md.append(f"# 5. Tam Edge Verification Gate'i çalıştır")
        md.append(f"python tools/gate.py . --base {report.base_branch} --track {report.track} --target-file {report.target_file}")
        md.append("```\n")

        return "\n".join(md)

    def generate_proposal(self, proposal: PlaybookProposal, output_path: Optional[Union[str, Path]] = None) -> Path:
        """
        Renders PlaybookProposal into markdown and saves to rules/playbooks/proposals/<name>.md.
        """
        if output_path:
            target_file = Path(output_path)
        else:
            self.proposals_dir.mkdir(parents=True, exist_ok=True)
            slug = proposal.domain_name.lower().replace(" ", "-")
            target_file = self.proposals_dir / f"{slug}-domain-proposal.md"

        target_file.parent.mkdir(parents=True, exist_ok=True)
        content = self.render_proposal_markdown(proposal)
        target_file.write_text(content, encoding="utf-8")
        return target_file

    def render_proposal_markdown(self, proposal: PlaybookProposal) -> str:
        """Renders GitHub Flavored Markdown for an emerging domain / crisis playbook proposal."""
        md = []

        md.append(f"# 📜 Operational Playbook Proposal: `{proposal.domain_name.upper()}` Domain Protocol\n")
        md.append("> [!NOTE]")
        md.append(f"> Bu taslak (proposal), canlı bir kriz / felaket kurtarma oturumu boyunca `edge-distill` Kara Kutusu (Flight Recorder) tarafından kaydedilen gerçek müdahalelerden ve git diff'lerinden damıtılmıştır.")
        md.append(f"> **Oturum ID:** `{proposal.crisis_context.get('session_id', 'N/A')}` | **Hedef:** {proposal.crisis_context.get('goal', 'N/A')}\n")
        md.append("---\n")

        # 1. Crisis Archetype
        md.append("## 🚨 1. Kriz Arketipi & İki Başlı Yapı Analizi (Divergence Analysis)\n")
        md.append(f"{proposal.summary}\n")
        div = proposal.two_headed_divergence_analysis
        md.append("| Boyut / Katman | Tespit Edilen Yapı / Durum |")
        md.append("| :--- | :--- |")
        md.append(f"| **1. Baş (Controller/API)** | {', '.join(f'`{f}`' for f in div.get('head_a_controller_layer', []))} |")
        md.append(f"| **2. Baş (Core/DB)** | {', '.join(f'`{f}`' for f in div.get('head_b_persistence_layer', []))} |")
        md.append(f"| **Test Seam Durumu** | {', '.join(f'`{f}`' for f in div.get('characterization_seams', []))} |")
        md.append(f"| **Uyuşmazlık Tanısı** | {div.get('divergence_nature', 'N/A')} |\n")
        md.append("> [!CAUTION]")
        md.append("> **Neden Standart Refactor veya Feature Domaini Yetmedi?**")
        md.append("> * `refactor` domaini davranışın 100% sabit olduğunu ve testlerin baştan yeşil olduğunu varsayar (Burada ise davranış iki başlıydı ve bug vardı).")
        md.append("> * `feature` domaini sıfırdan inşa varsayar (Burada ise zaten iki farklı implementasyon mevcuttu, sıfırdan yazmak 3. bir baş yaratırdı).\n")
        md.append("---\n")

        # 2. Chronological Flight Recorder
        md.append("## ⏱️ 2. Kronolojik Kara Kutu Günlüğü (Flight Recorder Log)\n")
        md.append("Kriz anından çözüm onayına kadar atılan deterministik adımlar:\n")
        if proposal.chronological_steps:
            for entry in proposal.chronological_steps:
                badge = f"[{entry.tag}]"
                md.append(f"- **`{entry.timestamp[:19]}`** `{badge:<16}` : {entry.step}")
        else:
            md.append("- Oturum boyunca kaydedilen adım bulunamadı.")
        md.append("\n---\n")

        # 3. Seam Recipes & Reconciliation
        md.append("## 🪡 3. Eksik Dikiş İnşası ve Senkronizasyon Reçetesi (Seam Strategy)\n")
        md.append("> [!TIP]")
        md.append("> **İki Başlı Yapıyı Birleştirirken İzlenen Deterministik Yol:**\n")
        for sr in proposal.seam_establishment_recipes:
            md.append(f"* {sr}")
        md.append("\n---\n")

        # 4. AST Diff Transformation
        if proposal.diff_patterns:
            dp = proposal.diff_patterns[0]
            md.append("## 🔄 4. Yapısal Konsolidasyon (Before vs After Architecture)\n")
            md.append("### ❌ ÖNCE: İki Başlı, Sızıntılı ve Şişkin Durum")
            md.append("```typescript")
            md.append(dp.before_code)
            md.append("```\n")
            md.append("### ✅ SONRA: Tek Başlı, Senkronize ve İzole SSOT Durumu")
            md.append("```typescript")
            md.append(dp.after_code)
            md.append("```\n")
            md.append("---\n")

        # 5. Proposed Rules for this Domain
        md.append(f"## 📜 5. Önerilen `{proposal.domain_name.upper()}` Domain Protokolü Kuralları\n")
        for rule in proposal.proposed_rules:
            md.append(f"* {rule}")
        md.append("\n---\n")

        # 6. Verification Checklist
        md.append("## ✅ 6. Çıkış Kriterleri ve Doğrulama Matrisi (Exit Criteria)\n")
        for item in proposal.verification_checklist:
            md.append(f"- [x] {item}")
        md.append("\n")

        return "\n".join(md)
