"""Submodule: report."""

import json

from tools.brigade.security.models import SecurityAuditReport

def _format_security_toon(report: SecurityAuditReport) -> str:
    header = (
        f"security_audit[{report.confirmed_count}]"
        f"{{scope:{report.scope_label},confirmed:{report.confirmed_count},"
        f"needs_validation:{report.needs_validation_count},rejected:{report.rejected_count},"
        f"ledger_covered:{report.ledger_covered}/{report.ledger_total},"
        f"passed:{str(report.passed).lower()}}}:"
    )
    lines = [header, "  id | verdict | severity | attack_class | entrypoint | sink | summary"]
    for f in report.findings:
        sev = f.severity or "none"
        summary = (f.rejection_reason or f.evidence or "").replace("\n", " ")[:60]
        lines.append(
            f"  {f.finding_id} | {f.verdict} | {sev} | {f.attack_class} | "
            f"{f.trace.get('entrypoint', '')} | {f.trace.get('sink', '')} | {summary}"
        )
    return "\n".join(lines)


def _format_security_markdown(report: SecurityAuditReport) -> str:
    icon = "✅" if report.passed else "❌"
    lines = [
        f"### Security & ABAC Audit ({icon} {report.confirmed_count} confirmed · {report.rejected_count} refuted)",
        f"- **Shared Ledger:** {report.ledger_covered}/{report.ledger_total} units covered · **Scope:** `{report.scope_label}`",
        "",
        "| id | verdict | severity | attack_class | entrypoint | sink |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for f in report.findings:
        lines.append(
            f"| `{f.finding_id}` | `{f.verdict}` | `{f.severity or 'none'}` | `{f.attack_class}` | `{f.trace.get('entrypoint', '')}` | `{f.trace.get('sink', '')}` |"
        )
    return "\n".join(lines)


def format_security_report(report: SecurityAuditReport, fmt: str = "toon") -> str:
    """Formats SecurityAuditReport as 'toon' (default), 'json', or 'markdown'."""
    mode = (fmt or "toon").strip().lower()
    if mode == "json":
        return json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
    if mode == "markdown":
        return _format_security_markdown(report)
    return _format_security_toon(report)
