"""Submodule: triage."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import json
import re

from tools.brigade.fsm import BrigadeFSM
from tools.brigade.models import CycleState, Ticket, TransitionLog
from tools.brigade.security.models import SecurityAuditReport, SecurityFinding, _write_json_atomic

def _slug_from_finding(f: SecurityFinding) -> str:
    base = Path(f.fix_target or "security").stem
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", f"{base}-{f.finding_id[-4:]}").strip("-")
    return cleaned.upper() or "FINDING"


def _build_security_ticket(f: SecurityFinding) -> Ticket:
    slug = _slug_from_finding(f)
    ticket_id = f"TICK-SEC-{slug}"
    ep = str(f.trace.get("entrypoint") or f.fix_target)
    parts = ep.split(":")
    line_num = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    target_file = f.fix_target or parts[0]
    return Ticket(
        ticket_id=ticket_id,
        track="core",
        domain="security",
        rule_id="SECURITY_AUDIT_CONFIRMED",
        severity="CRITICAL",
        target_file=target_file,
        line_number=line_num,
        fingerprint=f.fingerprint,
        description=f"[{f.attack_class}] {ep} -> {f.trace.get('sink')}: {f.evidence[:140]}",
        suggested_fix=f"Remediate {f.attack_class} sink '{f.trace.get('sink')}' in {target_file}.",
        branch_name=f"fix/sec-{slug.lower()}",
        expected_files=[target_file],
    )


def _upsert_core_ledger(repo: Path, tickets: List[Ticket]) -> None:
    ledger_path = repo / ".edge" / "ledger" / "core.json"
    data: Dict[str, Any] = {"version": "1.0.0", "track": "core", "items": []}
    if ledger_path.is_file():
        try:
            loaded = json.loads(ledger_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            pass
    items: List[Dict[str, Any]] = list(data.get("items") or [])
    for t in tickets:
        entry = {
            "ticket_id": t.ticket_id,
            "track": "core",
            "domain": "security",
            "rule_id": t.rule_id,
            "severity": t.severity,
            "file_path": t.target_file,
            "line_number": t.line_number,
            "fingerprint": t.fingerprint,
            "title": t.description[:90],
            "description": t.description,
            "suggested_fix": t.suggested_fix,
            "status": "OPEN",
            "created_at": t.created_at,
        }
        idx = next((i for i, it in enumerate(items) if it.get("ticket_id") == t.ticket_id or it.get("fingerprint") == t.fingerprint), None)
        if idx is not None:
            items[idx] = entry
        else:
            items.append(entry)
    data["items"] = items
    _write_json_atomic(ledger_path, data)


def triage_security_findings(repo_path: Path, report: SecurityAuditReport) -> List[str]:
    """Upserts CRITICAL TICK-SEC-* tickets into .edge/ledger/core.json and transitions IDLE FSM to TRIAGE."""
    repo = Path(repo_path).resolve()
    confirmed = [f for f in report.findings if f.verdict == "confirmed"]
    if not confirmed:
        return []
    tickets = [_build_security_ticket(f) for f in confirmed]
    _upsert_core_ledger(repo, tickets)

    fsm = BrigadeFSM(repo)
    if fsm.state.current_state == CycleState.IDLE:
        first = tickets[0]
        fsm.state.active_ticket = first
        fsm.state.active_branch = first.branch_name
        fsm.state.current_state = CycleState.TRIAGE
        fsm.state.history.append(
            TransitionLog(
                from_state=CycleState.IDLE.value,
                to_state=CycleState.TRIAGE.value,
                timestamp=datetime.now(timezone.utc).isoformat(),
                success=True,
                message=f"Auto-triaged confirmed security finding {first.ticket_id}.",
                details={"ticket_id": first.ticket_id, "source": "security_audit"},
            )
        )
        fsm.save()

    ids = [t.ticket_id for t in tickets]
    report.triage_tickets_created = ids
    return ids
