"""Ship-prep submodule: orchestrator_helpers."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.models import BrigadeState, Ticket
from tools.brigade.ship.models import IndexChange, SpecShipPlan
from tools.brigade.ship.paths_spec import _spec_slug_from_rel
from tools.brigade.ship.proof_meta import _proof_search_roots
from tools.brigade.ship.tickets import _resolve_spec_ticket_ids
from tools.brigade.ship.specs_candidates import _deduplicate_spec_candidates, _list_disk_spec_candidates
from tools.brigade.ship.specs import discover_changed_specs
from tools.brigade.ship.evidence import publish_screenshots_to_evidence_branch

def _discover_specs_and_tickets(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    receipts_by_ticket: Dict[str, Dict[str, Any]],
    issue_numbers: Optional[List[int]] = None,
    parent_issue: Optional[int] = None,
    offline: bool = False,
) -> Tuple[List[str], Dict[str, str], Dict[str, Optional[str]]]:
    from tools.brigade.ship_tracker import discover_tracker_spec_candidates

    disk_specs = _list_disk_spec_candidates(repo)
    ticket_map = _resolve_spec_ticket_ids(repo, eff_base, disk_specs, receipts_by_ticket)
    specs_linked = discover_changed_specs(
        repo, eff_base, changed_files, index_changes, ticket_map=ticket_map, history_receipts=receipts_by_ticket
    )
    tracker_cands = discover_tracker_spec_candidates(
        repo, issue_numbers=issue_numbers, parent_issue=parent_issue, offline=offline
    )
    if tracker_cands:
        specs_linked = _deduplicate_spec_candidates(repo, [*specs_linked, *tracker_cands])
    extra_specs = [s for s in specs_linked if s not in ticket_map]
    if extra_specs:
        ticket_map.update(_resolve_spec_ticket_ids(repo, eff_base, extra_specs, receipts_by_ticket))
    ticket_by_slug: Dict[str, Optional[str]] = {}
    for spec_rel in specs_linked:
        ticket_by_slug[_spec_slug_from_rel(spec_rel)] = ticket_map.get(spec_rel)
    return specs_linked, ticket_map, ticket_by_slug


def _maybe_publish_plan_evidence(
    repo: Path,
    publish_evidence: bool,
    failed_proofs: List[Dict[str, Any]],
    evidence_branch: str,
    selected_plans: List[SpecShipPlan],
    ticket: Optional[Ticket],
) -> Tuple[bool, str]:
    if not publish_evidence or failed_proofs:
        return True, ""
    return publish_screenshots_to_evidence_branch(
        repo, evidence_branch, selected_plans, _proof_search_roots(repo, ticket)
    )
