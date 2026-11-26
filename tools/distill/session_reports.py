"""
Terminal report formatters for edge-distill SessionMiner.
"""

from collections import Counter
from typing import Any, Dict, List

from tools.distill.session_paths import INTENT_DEFINITIONS


def _format_by_project_rows(projects: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    for proj_name, pinfo in sorted(projects.items(), key=lambda kv: kv[1]["session_count"], reverse=True):
        sess_list = pinfo.get("sessions", [])
        total_duration = sum(s.get("duration_minutes", 0) for s in sess_list)
        lines.append(f"\n📁 PROJE: {proj_name} ({pinfo['session_count']} Oturum, Toplam: {total_duration} dk)")
        lines.append("-" * 75)
        lines.append(f"  {'#':<3} | {'Konuşma ID':<10} | {'Başlangıç Tarihi':<20} | {'Süre(dk)':<8} | {'Adım':<6} | {'İnsan':<5} | Niyetler")
        lines.append("  " + "-" * 73)
        for i, s in enumerate(sess_list, 1):
            cid = s.get("conversation_id", "")[:8]
            st = s.get("start_time", "")
            dur = s.get("duration_minutes", 0)
            steps = s.get("total_steps", 0)
            turns = s.get("human_turns", 0)
            intents = ", ".join(s.get("detected_intents", [])) or "—"
            lines.append(f"  {i:<3} | {cid:<10} | {st:<20} | {dur:<8} | {steps:<6} | {turns:<5} | {intents}")
    return lines


def _format_summary_rows(projects: Dict[str, Any]) -> List[str]:
    lines = [
        f"{'Proje Adı':<25} | {'Oturum':<8} | {'Toplam Süre(dk)':<15} | En Sık Niyetler",
        "-" * 75,
    ]
    for proj_name, pinfo in sorted(projects.items(), key=lambda kv: kv[1]["session_count"], reverse=True):
        sess_list = pinfo.get("sessions", [])
        total_duration = sum(s.get("duration_minutes", 0) for s in sess_list)
        p_intents: Counter = Counter()
        for s in sess_list:
            for intent in s.get("detected_intents", []):
                p_intents[intent] += 1
        top_intents = ", ".join(f"{k}({v})" for k, v in p_intents.most_common(2)) or "—"
        lines.append(f"{proj_name:<25} | {pinfo['session_count']:<8} | {total_duration:<15} | {top_intents}")
    return lines


def format_sessions_report(data: Dict[str, Any], by_project: bool = False) -> str:
    """Formats a human-readable terminal report of sessions."""
    projects = data.get("projects", {})
    lines = [
        "=" * 75,
        "📊 ANTIGRAVITY TRANSCRIPT MINER — SESSION SUMMARY",
        "=" * 75,
        f"Oluşturulma Zamanı: {data.get('generated_at')}",
        f"Toplam Oturum:      {data.get('total_sessions', 0)}",
        f"Toplam Proje Sayısı:{len(projects)}",
        "-" * 75,
    ]
    if by_project:
        lines.extend(_format_by_project_rows(projects))
    else:
        lines.extend(_format_summary_rows(projects))
    lines.append("=" * 75)
    return "\n".join(lines)


def format_intents_report(data: Dict[str, Any]) -> str:
    """Formats the Intent & Directive Mirror Report (Ayna Raporu)."""
    total_sessions = data.get("total_sessions", 0)
    lines = [
        "=" * 75,
        "🧠 EDGE DISTILL — KULLANICI MİMARİ NİYET & SİTEM AYNASI (INTENT MIRROR)",
        "=" * 75,
        f"Toplam Taranan Oturum: {total_sessions}",
        "Kullanıcının En Çok Tembihlediği 5 Mimari Direktif Kümesi:",
        "-" * 75,
    ]
    summary = data.get("intent_summary", {})
    sorted_intents = sorted(summary.items(), key=lambda kv: kv[1].get("session_frequency", 0), reverse=True)
    for i, (intent_name, idata) in enumerate(sorted_intents, 1):
        freq = idata.get("session_frequency", 0)
        pct = (freq / total_sessions * 100) if total_sessions > 0 else 0.0
        defn = INTENT_DEFINITIONS.get(intent_name, {})
        title = defn.get("title", intent_name)
        rule_hint = defn.get("rule_hint", "rules/AGENTS.md")
        quote = idata.get("sample_quote", "")
        lines.append(f"\n{i}. 🎯 {title}")
        lines.append(f"   • Tekrarlanma Frekansı : {freq} oturumda (%{pct:.1f})")
        lines.append(f"   • Sisteme Kazınacak Kural : {rule_hint}")
        if quote:
            lines.append("   • Temsili Kullanıcı Alıntısı:")
            lines.append(f'     "{quote}"')
        else:
            lines.append("   • Temsili Kullanıcı Alıntısı: (Henüz bu kalıba rastlanmadı)")

    lines.extend([
        "\n" + "=" * 75,
        "💡 İPUCU: Sık tekrarlanan direktifleri 'coding_standards.md' ve ajan kurallarına",
        "   ekleyerek kullanıcının bilişsel tembih yükünü sıfırlayabilirsiniz.",
        "=" * 75,
    ])
    return "\n".join(lines)
