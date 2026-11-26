"""Ship-prep submodule: orchestrator_render."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import IndexChange, ShipPrepResult, SpecShipPlan
from tools.brigade.ship.realization_intent import _build_intent_str, _build_scenario_contract
from tools.brigade.ship.realization import compute_realization_audit
from tools.brigade.ship.render_markdown import _render_plan_bodies
from tools.brigade.ship.render_output import _render_top_level_bodies

def _assemble_ship_result(
    base_branch: str,
    head_branch: str,
    door_type: str,
    blast_radius: Dict[str, Any],
    index_changes: List[IndexChange],
    context_terms: List[str],
    specs_linked: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    changed_files: List[str],
    selected_plans: List[SpecShipPlan],
    sel_slug: Optional[str],
    gate_status: str,
    smoke_report: Optional[Dict[str, Any]] = None,
    security_report: Optional[Dict[str, Any]] = None,
    pr_issue_links: str = "",
) -> ShipPrepResult:
    spec_digests = [p.spec_digest for p in selected_plans if p.spec_digest]
    pr_body, show_me_body = _render_top_level_bodies(
        sel_slug, selected_plans, head_branch, base_branch, changed_files,
        index_changes, context_terms, specs_linked, verified_proofs, failed_proofs,
        examiner_receipt, gate_status, spec_digests, smoke_report=smoke_report, security_report=security_report,
        door_type=door_type, blast_radius=blast_radius, pr_issue_links=pr_issue_links,
    )
    return ShipPrepResult(
        base_branch=base_branch,
        head_branch=head_branch,
        door_type=door_type,
        blast_radius=blast_radius,
        index_changes=index_changes,
        context_terms=context_terms,
        specs_linked=specs_linked,
        verified_proofs=verified_proofs,
        failed_proofs=failed_proofs,
        examiner_receipt=examiner_receipt,
        intent=_build_intent_str(head_branch, index_changes, verified_proofs, changed_files, spec_digests=spec_digests),
        scenario_contract=_build_scenario_contract(head_branch, index_changes, verified_proofs, examiner_receipt, changed_files),
        pr_body=pr_body,
        show_me_body=show_me_body,
        spec_digests=spec_digests,
        spec_plans=selected_plans,
        selected_spec=sel_slug,
        smoke_report=smoke_report,
        security_report=security_report,
    )


def _render_selected_plans(
    repo: Path,
    selected_plans: List[SpecShipPlan],
    base_branch: str,
    context_terms: List[str],
    plan_receipts: Dict[str, Optional[Dict[str, Any]]],
    gate_status: str,
    door_type: str,
    blast_radius: Dict[str, Any],
    issue_numbers: Optional[List[int]],
    parent_issue: Optional[int],
) -> str:
    from tools.brigade.ship_tracker import format_pr_issue_links, resolve_pr_issue_refs

    for plan in selected_plans:
        refs, p_issue = resolve_pr_issue_refs(
            repo, issue_numbers=issue_numbers, parent_issue=parent_issue, spec_rel=plan.spec_path
        )
        plan_links = format_pr_issue_links(refs, p_issue)
        if plan.kind == "refactor":
            rec_ex = (plan.refactor_receipt or {}).get("seal_4_examiner") or None
            _render_plan_bodies(
                plan, base_branch, context_terms, rec_ex, gate_status,
                door_type=door_type, blast_radius=blast_radius, pr_issue_links=plan_links,
            )
        else:
            p_rec = plan_receipts.get(plan.spec_slug)
            plan.realization_audit = compute_realization_audit(plan, plan.spec_digest, p_rec)
            _render_plan_bodies(plan, base_branch, context_terms, p_rec, gate_status, pr_issue_links=plan_links)
    top_refs, top_parent = resolve_pr_issue_refs(repo, issue_numbers=issue_numbers, parent_issue=parent_issue)
    return format_pr_issue_links(top_refs, top_parent)
