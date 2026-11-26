"""Ship-prep submodule: orchestrator."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.models import BrigadeState, Ticket
from tools.brigade.ship.models import call_run_command
from tools.common import normalize_target_path
from tools.brigade.ship.models import IndexChange, ShipPrepResult, SpecShipPlan, _empty_result
from tools.brigade.ship.paths import _clean_slug
from tools.brigade.ship.context_index import _compute_search_tokens, _read_context_terms, parse_index_diff
from tools.brigade.ship.danger import classify_merge_danger
from tools.brigade.ship.topology_config import _get_head_branch, resolve_stage_branches
from tools.brigade.ship.topology import _collect_git_diff_bundle, _resolve_base_ref, validate_branch_topology
from tools.brigade.ship.brigade_snapshot import _load_brigade_history_snapshot
from tools.brigade.ship.proofs import _verify_scoped_proofs
from tools.brigade.ship.git_commits import _resolve_spec_commits
from tools.brigade.ship.git_branches import _apply_slice_commits_to_plans, _scope_plans_to_existing_ship_branches
from tools.brigade.ship.tier2 import _run_tier2_gates, _validate_ship_result
from tools.brigade.ship.plans import _build_all_spec_plans
from tools.brigade.ship.plans_refactor import _build_refactor_plans, _discover_refactor_receipts, _select_spec_plans
from tools.brigade.ship.orchestrator_helpers import _discover_specs_and_tickets, _maybe_publish_plan_evidence
from tools.brigade.ship.orchestrator_render import _assemble_ship_result, _render_selected_plans

def _evaluate_danger_with_receipts(
    changed_files: List[str], diff_stat: str, diff_text: str, head_branch: str,
    ticket: Optional[Ticket], refactor_receipts: List[Tuple[str, Dict[str, Any]]],
) -> Tuple[str, Dict[str, Any]]:
    is_refactor_slice = head_branch.startswith("refactor/") or bool(refactor_receipts) or (ticket is not None and getattr(ticket, "track", "") in ("core", "ui"))
    door_type, blast_radius = classify_merge_danger(changed_files, diff_stat, diff_text=diff_text, is_refactor=is_refactor_slice)
    for _, rec in refactor_receipts:
        s1 = rec.get("seal_1_intent") or {}
        for reason in s1.get("one_way_reasons") or []:
            if reason not in blast_radius["one_way_reasons"]:
                blast_radius["one_way_reasons"].append(reason)
        rec_door = str(s1.get("door_type") or "")
        if rec_door.startswith("One-way") and not door_type.startswith("One-way"):
            door_type = rec_door
    return door_type, blast_radius


def _build_and_select_ship_plans(
    repo: Path, eff_base: str, base_branch: str, changed_files: List[str],
    index_changes: List[IndexChange], context_terms: List[str], specs_linked: List[str],
    ticket: Optional[Ticket], ticket_map: Dict[str, Any], ticket_by_slug: Dict[str, Any],
    examiner_receipt: Optional[Dict[str, Any]], receipts_by_ticket: Dict[str, Dict[str, Any]],
    gate_status: str, refactor_receipts: List[Tuple[str, Dict[str, Any]]],
    door_type: str, blast_radius: Dict[str, Any], split_branches: bool, spec_slug: Optional[str],
) -> Tuple[bool, List[SpecShipPlan], Optional[str], str, List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Optional[Dict[str, Any]]]]:
    selected_slug = _clean_slug(spec_slug) if spec_slug else None
    verified_proofs, failed_proofs = _verify_scoped_proofs(
        repo, ticket, list(ticket_by_slug.keys()), changed_files,
        selected_slug=selected_slug, eff_base=eff_base, ticket_by_slug=ticket_by_slug,
    )
    spec_plans, plan_receipts = _build_all_spec_plans(
        repo, specs_linked, base_branch, changed_files, index_changes,
        context_terms, verified_proofs, failed_proofs, examiner_receipt, receipts_by_ticket, gate_status, ticket_map,
    )
    refactor_plans = _build_refactor_plans(
        refactor_receipts, base_branch, changed_files, index_changes,
        context_terms, gate_status, {p.pr_branch for p in spec_plans}, door_type, blast_radius,
    )
    all_plans = [*spec_plans, *refactor_plans]
    exclusive, has_shared, exc_files = _resolve_spec_commits(repo, eff_base, all_plans, ticket_map)
    _apply_slice_commits_to_plans(all_plans, exclusive, has_shared, exc_files, index_changes)
    if not split_branches:
        _scope_plans_to_existing_ship_branches(repo, eff_base, all_plans, index_changes)
    sel_ok, selected_plans, sel_slug, sel_err = _select_spec_plans(all_plans, spec_slug, eff_base)
    return sel_ok, selected_plans if sel_ok else all_plans, sel_slug, sel_err, verified_proofs, failed_proofs, plan_receipts


def _prepare_ship_diff_context(
    repo: Path, base_branch: str, split_branches: bool, allow_topology_override: bool, stage_branches: Optional[Dict[str, str]]
) -> Tuple[bool, str, str, Dict[str, str], List[str], str, str, str]:
    head_branch = _get_head_branch(repo)
    eff_stages = resolve_stage_branches(repo, stage_branches)
    topo_ok, topo_err = validate_branch_topology(base_branch, head_branch, split_branches=split_branches, allow_override=allow_topology_override, stage_branches=eff_stages)
    if not topo_ok:
        return False, head_branch, "", eff_stages, [], "", "", topo_err
    eff_base = _resolve_base_ref(repo, base_branch, head_branch=head_branch, stage_branches=eff_stages)
    if not eff_base:
        return False, head_branch, "", eff_stages, [], "", "", f"Git base branch '{base_branch}' not found in {repo}."
    diff_ok, head_branch, changed_files, diff_stat, idx_diff, diff_err = _collect_git_diff_bundle(repo, eff_base)
    if not diff_ok:
        return False, head_branch, eff_base, eff_stages, [], "", "", diff_err
    return True, head_branch, eff_base, eff_stages, changed_files, diff_stat, idx_diff, ""


def prepare_ship_payload(
    repo_path: Path, base_branch: str = "development", strict_proofs: bool = False,
    spec_slug: Optional[str] = None, split_branches: bool = False, publish_evidence: bool = False,
    evidence_branch: str = "edge-qa-evidence", require_smoke: bool = False,
    allow_topology_override: bool = False, stage_branches: Optional[Dict[str, str]] = None,
    issue_numbers: Optional[List[int]] = None, parent_issue: Optional[int] = None, offline: bool = False,
) -> Tuple[bool, ShipPrepResult, str]:
    """Collects per-spec and refactor ship plans, scoped ProofVerifier results, optional evidence publishing, and PR bodies."""
    repo = normalize_target_path(repo_path)
    ok, head_branch, eff_base, eff_stages, changed_files, diff_stat, idx_diff, err = _prepare_ship_diff_context(
        repo, base_branch, split_branches, allow_topology_override, stage_branches
    )
    if not ok:
        return False, _empty_result(base_branch, head_branch), err
    _, diff_text, _ = call_run_command(["git", "diff", f"{eff_base}..HEAD"], cwd=repo)
    index_changes = parse_index_diff(idx_diff)
    ticket, examiner_receipt, gate_status, receipts_by_ticket = _load_brigade_history_snapshot(repo)
    refactor_receipts = _discover_refactor_receipts(repo, changed_files)
    door_type, blast_radius = _evaluate_danger_with_receipts(changed_files, diff_stat, diff_text, head_branch, ticket, refactor_receipts)
    context_terms = _read_context_terms(repo, _compute_search_tokens(blast_radius, index_changes))
    specs_linked, ticket_map, ticket_by_slug = _discover_specs_and_tickets(
        repo, eff_base, changed_files, index_changes, receipts_by_ticket,
        issue_numbers=issue_numbers, parent_issue=parent_issue, offline=offline,
    )
    sel_ok, plans, sel_slug, sel_err, verified_proofs, failed_proofs, plan_receipts = _build_and_select_ship_plans(
        repo, eff_base, base_branch, changed_files, index_changes, context_terms, specs_linked,
        ticket, ticket_map, ticket_by_slug, examiner_receipt, receipts_by_ticket, gate_status,
        refactor_receipts, door_type, blast_radius, split_branches, spec_slug,
    )
    if not sel_ok:
        res_err = _empty_result(base_branch, head_branch)
        res_err.spec_plans, res_err.selected_spec = plans, sel_slug
        return False, res_err, sel_err
    pub_ok, pub_err = _maybe_publish_plan_evidence(repo, publish_evidence, failed_proofs, evidence_branch, plans, ticket)
    if not pub_ok:
        res_pub = _empty_result(base_branch, head_branch)
        res_pub.spec_plans, res_pub.verified_proofs = plans, verified_proofs
        return False, res_pub, pub_err
    top_links = _render_selected_plans(repo, plans, base_branch, context_terms, plan_receipts, gate_status, door_type, blast_radius, issue_numbers, parent_issue)
    smoke_report, sec_report, gate_err = _run_tier2_gates(repo, base_branch, eff_base, changed_files, require_smoke, eff_stages)
    result = _assemble_ship_result(
        base_branch, head_branch, door_type, blast_radius, index_changes, context_terms,
        specs_linked, verified_proofs, failed_proofs, examiner_receipt, changed_files,
        plans, sel_slug, gate_status, smoke_report=smoke_report, security_report=sec_report, pr_issue_links=top_links,
    )
    return _validate_ship_result(result, strict_proofs, split_branches, repo, eff_base, ticket_map=ticket_map, gate_err=gate_err)
