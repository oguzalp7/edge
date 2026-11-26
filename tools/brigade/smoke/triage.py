"""Submodule: triage."""

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json

from tools.brigade.fsm import BrigadeFSM
from tools.brigade.models import CycleState, Ticket, TransitionLog
from tools.brigade.smoke.constants import _write_json_atomic
from tools.brigade.smoke.models import RouteSmokeResult, SmokeScanReport
from tools.brigade.smoke.tickets import _build_perf_ticket, _build_smoke_ticket, _ticket_to_ledger_item

def _load_ui_ledger_data(ledger_path: Path) -> Dict[str, Any]:
    if not ledger_path.is_file():
        return {"version": "1.0.0", "track": "ui", "items": []}
    try:
        loaded = json.loads(ledger_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return {"version": "1.0.0", "track": "ui", "items": []}


def _upsert_ui_ledger(repo: Path, pairs: List[tuple[Ticket, RouteSmokeResult]]) -> None:
    ledger_path = repo / ".edge" / "ledger" / "ui.json"
    data = _load_ui_ledger_data(ledger_path)
    items: List[Dict[str, Any]] = list(data.get("items") or [])
    for ticket, res in pairs:
        entry = _ticket_to_ledger_item(ticket, res)
        idx = next(
            (i for i, it in enumerate(items) if it.get("ticket_id") == ticket.ticket_id or it.get("fingerprint") == ticket.fingerprint),
            None,
        )
        if idx is not None:
            items[idx] = entry
        else:
            items.append(entry)
    data["items"] = items
    _write_json_atomic(ledger_path, data)


def _activate_triage_if_idle(repo: Path, tickets: List[Ticket]) -> None:
    if not tickets:
        return
    fsm = BrigadeFSM(repo)
    if fsm.state.current_state != CycleState.IDLE:
        return
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
            message=f"Auto-triaged smoke failure {first.ticket_id} ({first.target_file}).",
            details={"ticket_id": first.ticket_id, "source": "smoke_routes"},
        )
    )
    fsm.save()


def _select_priority_triage_ticket(
    tier_a: List[tuple[Ticket, RouteSmokeResult]],
    tier_b: List[tuple[Ticket, RouteSmokeResult]],
) -> Optional[Ticket]:
    if tier_a:
        return tier_a[0][0]
    if tier_b:
        slowest = max(tier_b, key=lambda pair: (pair[1].settle_ms, pair[1].heap_used_mb))
        return slowest[0]
    return None


def triage_smoke_failures(repo_path: Path, report: SmokeScanReport) -> List[str]:
    """Creates idempotent CRITICAL TICK-SMOKE-* and WARNING TICK-PERF-* ledger tickets and starts TRIAGE."""
    repo = Path(repo_path)
    tier_a_routes = [r for r in report.results if not r.navigable or r.perf_status == "FAIL_STUCK"]
    tier_b_routes = [
        r for r in report.results if r.navigable and r.perf_status in ("WARN_SLOW", "WARN_MEMORY")
    ]
    if not tier_a_routes and not tier_b_routes:
        return []

    tier_a_pairs = [(_build_smoke_ticket(res), res) for res in tier_a_routes]
    tier_b_pairs = [(_build_perf_ticket(res, report), res) for res in tier_b_routes]
    all_pairs = [*tier_a_pairs, *tier_b_pairs]
    _upsert_ui_ledger(repo, all_pairs)

    primary = _select_priority_triage_ticket(tier_a_pairs, tier_b_pairs)
    if primary:
        _activate_triage_if_idle(repo, [primary])

    created_ids = [t.ticket_id for t, _ in all_pairs]
    report.triage_tickets_created = created_ids
    _write_json_atomic(repo / ".edge" / "qa" / "smoke-routes.json", report.to_dict())
    return created_ids
