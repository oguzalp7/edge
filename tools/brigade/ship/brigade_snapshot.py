"""Ship-prep submodule: brigade_snapshot."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json

from tools.brigade.models import BrigadeState, Ticket
from tools.brigade.tasks_bridge import resolve_target_repo_root
from tools.brigade.ship.constants import _TICKET_RE

def _resolve_entry_ticket_id(entry: Any, rec_raw: Dict[str, Any]) -> Optional[str]:
    tid = rec_raw.get("ticket_id") or entry.details.get("ticket_id")
    if tid:
        return str(tid).strip()
    m = _TICKET_RE.search(entry.message or "")
    return m.group(1) if m else None


def _extract_examiner_receipts_by_ticket(state: BrigadeState) -> Dict[str, Dict[str, Any]]:
    """Recovers per-ticket ExaminerReceipt dicts from history entries and active examiner_receipt."""
    receipts: Dict[str, Dict[str, Any]] = {}
    for entry in state.history:
        details = entry.details if isinstance(entry.details, dict) else {}
        rec_raw = details.get("examiner_receipt")
        if not isinstance(rec_raw, dict):
            continue
        tid = _resolve_entry_ticket_id(entry, rec_raw)
        if tid:
            receipts[tid] = dict(rec_raw)
    if state.examiner_receipt:
        rec_dict = state.examiner_receipt.to_dict()
        fallback_tid = state.active_ticket.ticket_id if state.active_ticket else None
        tid = rec_dict.get("ticket_id") or fallback_tid
        if tid:
            receipts[str(tid)] = rec_dict
    return receipts


def _extract_gate_status(state: BrigadeState) -> str:
    for entry in reversed(state.history):
        if entry.from_state == "GATE" or entry.to_state == "GATE":
            status_word = "PASSED" if entry.success else "FAILED"
            return f"{status_word} ({entry.message})"
    return "No GATE transition logged"


def _load_brigade_history_snapshot(
    repo: Path,
) -> Tuple[Optional[Ticket], Optional[Dict[str, Any]], str, Dict[str, Dict[str, Any]]]:
    state_file = repo / ".edge" / "brigade.json"
    if not state_file.is_file():
        common_root = resolve_target_repo_root(repo)
        alt_file = common_root / ".edge" / "brigade.json"
        if alt_file.is_file():
            state_file = alt_file
        else:
            return None, None, "Not recorded", {}
    try:
        raw = json.loads(state_file.read_text(encoding="utf-8"))
        state = BrigadeState.from_dict(raw)
    except Exception:
        return None, None, "Unreadable .edge/brigade.json", {}

    receipts_by_ticket = _extract_examiner_receipts_by_ticket(state)
    receipt_dict = state.examiner_receipt.to_dict() if state.examiner_receipt else None
    if not receipt_dict and receipts_by_ticket:
        receipt_dict = list(receipts_by_ticket.values())[-1]
    return state.active_ticket, receipt_dict, _extract_gate_status(state), receipts_by_ticket


def _load_brigade_snapshot(repo: Path) -> Tuple[Optional[Ticket], Optional[Dict[str, Any]], str]:
    ticket, receipt_dict, gate_status, _ = _load_brigade_history_snapshot(repo)
    return ticket, receipt_dict, gate_status
