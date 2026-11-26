"""Markdown report and zero-amnesia prompt alert formatting for FlightRecorder."""

from typing import Any, Dict, List

_STATUS_ICONS = {
    "ACTIVE": "🟢 ACTIVE",
    "PAUSED_ESCALATED": "⏸️ PAUSED (ESCALATED)",
    "TERMINATED": "🛑 TERMINATED (ABORTED)",
    "RESOLVED": "✅ RESOLVED & LANDED",
    "STAGNATED": "⚠️ STAGNATED",
}


def format_prompt_alert_block(data: Dict[str, Any]) -> str:
    """Format a zero-amnesia negative constraints block for station prompts."""
    dead_ends = data.get("dead_ends", [])
    escalations = [e for e in data.get("escalations", []) if e.get("decision")]
    if not dead_ends and not escalations:
        return ""
    lines = [
        "\n> [!CAUTION]",
        "> ### 🚫 ZERO-AMNESIA FLIGHT RECORDER: PREVIOUS DEAD-ENDS & CONSTRAINTS",
        "> The following approaches were already tried and proven FATAL. DO NOT REPEAT THEM:",
    ]
    for de in dead_ends:
        lines.append(f"> - **[{de['id']} - {de['title']}]:** {de['prohibited_rule']}")
        lines.append(f">   *Why it failed:* {de['reason']}")
    if escalations:
        lines.extend([">", "> ### 👑 BINDING CAPTAIN DECISIONS:"])
        lines.extend(f"> - **Decision:** {esc['decision']} *(Context: {esc['reason']})*" for esc in escalations)
    lines.append("")
    return "\n".join(lines)


def _resolve_target_display(data: Dict[str, Any]) -> str:
    if data.get("target_file"):
        return str(data["target_file"])
    if data.get("expected_files"):
        return ", ".join(data["expected_files"])
    return "(dynamic-slice)"


def _render_dead_ends(md: List[str], dead_ends: List[Dict[str, Any]]) -> None:
    if not dead_ends:
        md.append("*Henüz kaydedilmiş negatif kısıt bulunmuyor.*")
        return
    for de in dead_ends:
        md.extend([
            f"### ❌ {de['id']}: {de['title']}",
            f"* **Neden Başarısız Oldu:** {de['reason']}",
            f"* **Yasaklı Kural (Constraint):** `{de['prohibited_rule']}`",
        ])
        if de.get("failure_output"):
            md.append(f"```text\n{de['failure_output']}\n```")
        md.append("")


def _render_escalations(md: List[str], escalations: List[Dict[str, Any]]) -> None:
    if not escalations:
        md.append("*Henüz eskalasyon yaşanmadı.*")
        return
    for i, esc in enumerate(escalations, 1):
        decision_str = f"**Cevap:** {esc['decision']}" if esc.get("decision") else "*(Henüz Cevaplanmadı - BEKLEMEDE)*"
        md.extend([f"{i}. **Soru / Neden ({esc['timestamp']}):** {esc['reason']}", f"   - {decision_str}", ""])


def _render_attempts(md: List[str], attempts: List[Dict[str, Any]]) -> None:
    if not attempts:
        md.append("*Henüz deneme kaydı yok.*")
        return
    for att in attempts:
        icon = "🟢" if att["exit_code"] == 0 else "🔴"
        md.append(f"* {icon} **Attempt {att['attempt_num']}** (Exit: {att['exit_code']}) - `{att['timestamp']}`")
        md.append(f"  * {att['summary']}")
        if att.get("diff_stat"):
            md.append(f"  * Diff: `{att['diff_stat']}`")


def _render_guard_failures(md: List[str], guard_failures: List[Dict[str, Any]]) -> None:
    if not guard_failures:
        return
    md.extend(["---", "", "## 🛡️ Guard Failures & Verification Blocks"])
    for gf in guard_failures:
        md.append(f"* **[{gf.get('state')}]** (`{gf.get('timestamp')}`): {gf.get('message')}")
        if gf.get("details"):
            md.append(f"  * Details: `{gf.get('details')}`")
    md.append("")


def _render_review_findings(md: List[str], review_findings: List[Dict[str, Any]]) -> None:
    if not review_findings:
        return
    md.extend(["---", "", "## 🧐 Examiner Review Findings Ledger"])
    for rf in review_findings:
        line = f":{rf.get('line_number')}" if rf.get("line_number") is not None else ""
        md.append(f"* **[{rf.get('severity', 'INFO')}] [{rf.get('axis', 'standards').upper()}]** `{rf.get('file_path', '')}{line}`: {rf.get('description')}")
        if rf.get("rule"):
            md.append(f"  * Rule: `{rf.get('rule')}`")
        if rf.get("suggested_fix"):
            md.append(f"  * Suggested Fix: {rf.get('suggested_fix')}")
    md.append("")


def render_flight_markdown(ticket_id: str, data: Dict[str, Any]) -> str:
    """Render full FlightRecorder living Markdown post-mortem document."""
    md = [
        f"# 📓 Flight Recorder: [{ticket_id}]",
        f"- **Status:** {_STATUS_ICONS.get(data['status'], data['status'])}",
        f"- **Track / Domain:** `{data.get('track')}` / `{data.get('domain')}`",
        f"- **Target File:** `{_resolve_target_display(data)}`",
        f"- **Worktree Path:** `{data.get('worktree_path') or 'N/A'}`",
        f"- **Last Updated:** `{data.get('updated_at')}`",
        "",
        "---",
        "",
        "## 🚫 Negatif Kısıtlar & Çıkmaz Yollar (Dead Ends)",
    ]
    if data.get("expected_files"):
        md.insert(4, f"- **Expected Files:** `{', '.join(data['expected_files'])}`")
    _render_dead_ends(md, data.get("dead_ends", []))
    md.extend(["---", "", "## ⏸️ Escalation & İnsan Kararları (Captain Calls)"])
    _render_escalations(md, data.get("escalations", []))
    md.extend(["---", "", "## 📊 Deneme Geçmişi (Attempt History)"])
    _render_attempts(md, data.get("attempts", []))
    _render_guard_failures(md, data.get("guard_failures", []))
    _render_review_findings(md, data.get("review_findings", []))
    return "\n".join(md) + "\n"
