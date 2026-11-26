"""Ship-prep submodule: render_evidence."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json

from tools.brigade.ship.paths import _format_screenshot_title
from tools.brigade.ship.render_examiner import _format_examiner_seal_block, _format_refactor_evidence_block

def _format_proof_line(p: Dict[str, Any]) -> List[str]:
    shots = len(p.get("screenshot_hashes", {}))
    out = [
        f"- **QA Proof `{p['slug']}`:** ✅ Verified (`persistence_verified: true`, `console_clean: true`, `{shots}` SHA-256 verified screenshot(s))"
    ]
    visited = p.get("visited_urls") or []
    if visited:
        routes = " · ".join(f"`{u}`" for u in visited)
        out.append(f"- **Visited Routes:** {routes}")
    actions = p.get("user_actions_executed") or []
    if actions:
        out.extend([f"<details><summary>⚡ Executed E2E Actions ({len(actions)} steps)</summary>", ""])
        out.extend(f"{idx}. {act}" for idx, act in enumerate(actions, 1))
        out.extend(["", "</details>"])
    db_cc = p.get("db_crosscheck")
    if db_cc:
        pretty_json = json.dumps(db_cc, indent=2, ensure_ascii=False)
        out.extend(["<details><summary>🗄️ Database & State Cross-Check</summary>", "", "```json", pretty_json, "```", "", "</details>"])
    urls = p.get("screenshot_urls") or []
    if urls:
        out.extend(["", "#### Visual Evidence Gallery"])
        for url in urls:
            title = _format_screenshot_title(str(url))
            fname = Path(str(url).split("?")[0]).name or "screenshot.png"
            out.extend([f"- **{title}**", f"  ![{fname}]({url})"])
    return out


def _smoke_metric(smoke_report: Dict[str, Any], key: str, cast: Any, default: Any) -> Any:
    val = smoke_report.get(key)
    return cast(default if val is None else val)


def _format_smoke_audit_block(smoke_report: Optional[Dict[str, Any]]) -> List[str]:
    if not smoke_report:
        return []
    passed = _smoke_metric(smoke_report, "passed_routes", int, 0)
    total = _smoke_metric(smoke_report, "total_routes", int, 0)
    c_errs = _smoke_metric(smoke_report, "total_console_errors", int, 0)
    p_errs = _smoke_metric(smoke_report, "total_page_errors", int, 0)
    slow = _smoke_metric(smoke_report, "slow_routes", int, 0)
    stuck = _smoke_metric(smoke_report, "stuck_routes", int, 0)
    max_settle = _smoke_metric(smoke_report, "max_settle_ms", int, 0)
    max_heap = _smoke_metric(smoke_report, "max_heap_mb", float, 0.0)
    icon = "✅" if smoke_report.get("all_navigable") else "❌"
    return [
        "",
        "### Route Navigability & Console Smoke Audit",
        f"- {icon} {passed}/{total} routes navigable · {c_errs} console errors · {p_errs} page errors",
        f"- Telemetry: slow={slow} · stuck={stuck} · max_settle={max_settle}ms · max_heap={max_heap}MB",
    ]


def _format_security_audit_block(security_report: Optional[Dict[str, Any]]) -> List[str]:
    if not security_report:
        return []
    confirmed = _smoke_metric(security_report, "confirmed_count", int, 0)
    rejected = _smoke_metric(security_report, "rejected_count", int, 0)
    covered = _smoke_metric(security_report, "ledger_covered", int, 0)
    total = _smoke_metric(security_report, "ledger_total", int, 0)
    icon = "✅" if security_report.get("passed") else "❌"
    return [
        "",
        "### Security & ABAC Audit",
        f"- {icon} {confirmed} confirmed vulnerabilities · {rejected} refuted · Shared Ledger: {covered}/{total} units covered",
    ]


def _format_evidence_section(
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    smoke_report: Optional[Dict[str, Any]] = None,
    security_report: Optional[Dict[str, Any]] = None,
    refactor_receipts: Optional[List[Dict[str, Any]]] = None,
) -> List[str]:
    lines = ["", "## Evidence"]
    if specs_linked:
        lines.append(f"- **Specs:** {', '.join(f'`{s}`' for s in specs_linked)}")
    lines.append(f"- **Gate Status:** {gate_status}")
    if refactor_receipts:
        lines.extend(_format_refactor_evidence_block(refactor_receipts))
        if examiner_receipt:
            lines.extend(_format_examiner_seal_block(examiner_receipt))
    else:
        lines.extend(_format_examiner_seal_block(examiner_receipt))
    if verified_proofs or failed_proofs:
        lines.extend(["", "### Live QA Proof & Visual Evidence"])
        for p in verified_proofs:
            lines.extend(_format_proof_line(p))
        for fp in failed_proofs:
            lines.append(f"- **QA Proof `{fp['slug']}` (FAILED - {fp['error']}):** {fp['message']}")
    lines.extend(_format_smoke_audit_block(smoke_report))
    lines.extend(_format_security_audit_block(security_report))
    return lines
