"""Ship-prep submodule: tickets_receipts."""

from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.tickets_proofs import _receipt_matches_spec

def _proof_belongs_to_plan(
    proof: Dict[str, Any],
    spec_slug: str,
    ticket_id: Optional[str],
) -> bool:
    if proof.get("spec_slug") == spec_slug:
        return True
    if ticket_id and proof.get("ticket_id") == ticket_id:
        return True
    return not proof.get("spec_slug") and proof.get("slug") == spec_slug


def _resolve_active_receipt(
    plan_ticket_id: Optional[str],
    spec_slug: str,
    spec_rel: str,
    examiner_receipt: Optional[Dict[str, Any]],
    total_plans: int,
) -> Optional[Dict[str, Any]]:
    if not examiner_receipt:
        return None
    rec_tid = examiner_receipt.get("ticket_id")
    if rec_tid:
        return examiner_receipt if rec_tid == plan_ticket_id else None
    if total_plans == 1 or _receipt_matches_spec(examiner_receipt, spec_rel, spec_slug):
        return examiner_receipt
    return None


def _resolve_plan_receipt(
    plan_ticket_id: Optional[str],
    spec_slug: str,
    spec_rel: str,
    examiner_receipt: Optional[Dict[str, Any]],
    receipts_by_ticket: Dict[str, Dict[str, Any]],
    total_plans: int,
) -> Optional[Dict[str, Any]]:
    if plan_ticket_id and plan_ticket_id in receipts_by_ticket:
        return receipts_by_ticket[plan_ticket_id]
    active = _resolve_active_receipt(plan_ticket_id, spec_slug, spec_rel, examiner_receipt, total_plans)
    if active:
        return active
    if total_plans == 1 and receipts_by_ticket:
        return list(receipts_by_ticket.values())[-1]
    return None
