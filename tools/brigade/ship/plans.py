"""Ship-prep submodule: plans."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.models import IndexChange, SpecShipPlan
from tools.brigade.ship.paths import _filter_plan_index_changes, _match_expected_files, _norm_rel_path
from tools.brigade.ship.paths_spec import _resolve_spec_file_path, _spec_slug_from_rel
from tools.brigade.ship.spec_parser import parse_spec_document
from tools.brigade.ship.spec_expected import _expand_expected_globs, _extract_spec_expected_files
from tools.brigade.ship.tickets_receipts import _proof_belongs_to_plan, _resolve_plan_receipt
from tools.brigade.ship.realization import compute_realization_audit
from tools.brigade.ship.render_markdown import _render_plan_bodies

def _clean_pr_title(spec_slug: str, raw_title: str, kind: str = "spec") -> str:
    cleaned = re.sub(r"^[^\w\s]+\s*", "", raw_title or "").strip()
    cleaned = re.sub(r"^(Edge Brigade Specification|Specification|Spec)\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    summary = cleaned or f"deliver {spec_slug}"
    prefix = f"refactor({spec_slug}): " if kind == "refactor" else f"feat({spec_slug}): "
    full = f"{prefix}{summary}"
    if len(full) <= 96:
        return full
    budget = 93 - len(prefix)
    if budget <= 0:
        return full[:93].rstrip() + "..."
    candidate = summary[:budget]
    if len(summary) > budget and not summary[budget].isspace() and " " in candidate:
        candidate = candidate.rsplit(" ", 1)[0]
    trimmed = candidate.rstrip(" &-:,/;(\t")
    if not trimmed:
        trimmed = summary[:budget].rstrip()
    return f"{prefix}{trimmed}..."


def _append_proof_matched_files(matched: List[str], proofs: List[Dict[str, Any]]) -> None:
    for vp in proofs:
        if vp.get("path") and vp["path"] not in matched:
            matched.append(vp["path"])
        for sp in vp.get("screenshot_paths", []):
            norm_sp = _norm_rel_path(str(sp))
            if norm_sp not in matched:
                matched.append(norm_sp)


def _build_single_spec_plan(
    repo: Path,
    spec_rel: str,
    base_branch: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    context_terms: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    gate_status: str,
    ticket_id: Optional[str] = None,
) -> SpecShipPlan:
    spec_file = _resolve_spec_file_path(repo, spec_rel)
    spec_slug = _spec_slug_from_rel(spec_rel)
    digest = parse_spec_document(spec_file, rel_path=spec_rel)
    expected = _extract_spec_expected_files(spec_file)
    matched = _match_expected_files(_expand_expected_globs(expected, changed_files), changed_files)
    if spec_rel not in matched:
        matched.append(spec_rel)

    plan_v_proofs = [p for p in verified_proofs if _proof_belongs_to_plan(p, spec_slug, ticket_id)]
    plan_f_proofs = [p for p in failed_proofs if _proof_belongs_to_plan(p, spec_slug, ticket_id)]
    _append_proof_matched_files(matched, plan_v_proofs)

    plan = SpecShipPlan(
        spec_slug=spec_slug,
        spec_path=spec_rel,
        pr_branch=f"ship/{spec_slug}",
        pr_title=_clean_pr_title(spec_slug, digest.title),
        expected_files=expected,
        matched_files=matched,
        index_changes=_filter_plan_index_changes(index_changes, spec_slug, spec_rel, matched),
        verified_proofs=plan_v_proofs,
        failed_proofs=plan_f_proofs,
        spec_digest=digest,
        ticket_id=ticket_id,
    )
    plan.realization_audit = compute_realization_audit(plan, digest, examiner_receipt)
    _render_plan_bodies(plan, base_branch, context_terms, examiner_receipt, gate_status)
    return plan


def _build_all_spec_plans(
    repo: Path,
    specs_linked: List[str],
    base_branch: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    context_terms: List[str],
    verified_proofs: List[Dict[str, Any]],
    failed_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    receipts_by_ticket: Dict[str, Dict[str, Any]],
    gate_status: str,
    ticket_map: Dict[str, str],
) -> Tuple[List[SpecShipPlan], Dict[str, Optional[Dict[str, Any]]]]:
    plans: List[SpecShipPlan] = []
    plan_receipts: Dict[str, Optional[Dict[str, Any]]] = {}
    total = len(specs_linked)
    for spec_rel in specs_linked:
        tid = ticket_map.get(spec_rel)
        slug = _spec_slug_from_rel(spec_rel)
        p_rec = _resolve_plan_receipt(tid, slug, spec_rel, examiner_receipt, receipts_by_ticket, total)
        plan_receipts[slug] = p_rec
        plans.append(
            _build_single_spec_plan(
                repo, spec_rel, base_branch, changed_files, index_changes,
                context_terms, verified_proofs, failed_proofs, p_rec, gate_status, ticket_id=tid,
            )
        )
    return plans, plan_receipts
