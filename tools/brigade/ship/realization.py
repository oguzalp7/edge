"""Ship-prep submodule: realization."""

from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.models import RealizationAudit, SpecDigest, SpecShipPlan
from tools.brigade.ship.paths import _is_evidence_artifact_path, _normalize_display_path
from tools.brigade.ship.realization_intent import _build_file_tree_diff, _classify_audit_files

def _collect_proof_evidence_text(verified_proofs: List[Dict[str, Any]]) -> Tuple[List[str], List[str]]:
    checklist_items: List[str] = []
    action_items: List[str] = []
    for p in verified_proofs:
        dc = p.get("directives_checklist")
        if isinstance(dc, dict):
            checklist_items.extend(f"{k}: {v}" for k, v in dc.items())
        elif isinstance(dc, list):
            checklist_items.extend(str(item) for item in dc)
        action_items.extend(str(a) for a in p.get("user_actions_executed", []) or [])
        action_items.extend(str(u) for u in p.get("visited_urls", []) or [])
        db_cc = p.get("db_crosscheck")
        if isinstance(db_cc, dict):
            action_items.extend(str(k) for k in db_cc.keys())
    return checklist_items, action_items


def _tokens_overlap(crit_id: str, exp_text: str, haystack: str) -> bool:
    if crit_id.lower() in haystack:
        return True
    words = [w for w in re.findall(r"[a-z0-9]{4,}", exp_text.lower())]
    if not words:
        return False
    hits = sum(1 for w in words if w in haystack)
    return hits >= min(2, len(words))


def _evaluate_single_criterion(
    crit: Dict[str, str],
    checklist_items: List[str],
    action_items: List[str],
    code_haystack: str,
    has_pass_seal: bool,
    has_realized: bool,
) -> Dict[str, str]:
    cid = crit["id"]
    exp = crit.get("expectation") or crit.get("title") or cid
    chk_hay = "\n".join(checklist_items).lower()
    act_hay = "\n".join(action_items).lower()
    if _tokens_overlap(cid, exp, chk_hay):
        return {"id": cid, "expectation": exp, "status": "✅ Verified", "evidence": "QA directives_checklist"}
    if _tokens_overlap(cid, exp, act_hay):
        return {"id": cid, "expectation": exp, "status": "✅ Verified", "evidence": "QA action / route / DB cross-check"}
    if has_pass_seal and has_realized:
        return {"id": cid, "expectation": exp, "status": "✅ Verified", "evidence": "Examiner PASS seal & realized files"}
    if _tokens_overlap(cid, exp, code_haystack) or has_pass_seal:
        return {"id": cid, "expectation": exp, "status": "☑️ Implemented", "evidence": "Diff / code realization"}
    return {"id": cid, "expectation": exp, "status": "⚠️ Unverified", "evidence": "No matching proof or code trace"}


def _build_criteria_rows(
    digest: Optional[SpecDigest],
    plan: SpecShipPlan,
    examiner_receipt: Optional[Dict[str, Any]],
    actual_code_files: List[str],
    realized_files: List[str],
) -> List[Dict[str, str]]:
    if not digest or not digest.acceptance_criteria:
        return []
    checklist_items, action_items = _collect_proof_evidence_text(plan.verified_proofs)
    has_pass = bool(examiner_receipt and str(examiner_receipt.get("verdict") or "").upper() == "PASS")
    code_parts = [*actual_code_files, *(f"{c.kind} {c.symbol}" for c in plan.index_changes)]
    if examiner_receipt:
        code_parts.append(str(examiner_receipt.get("summary") or ""))
    code_haystack = "\n".join(code_parts).lower()
    return [
        _evaluate_single_criterion(c, checklist_items, action_items, code_haystack, has_pass, bool(realized_files))
        for c in digest.acceptance_criteria
    ]


def _extract_actual_code_files(matched_files: List[str]) -> List[str]:
    actual: List[str] = []
    for raw_path in matched_files:
        if _is_evidence_artifact_path(raw_path):
            continue
        norm = _normalize_display_path(raw_path).lstrip("/")
        if norm and norm not in actual:
            actual.append(norm)
    return actual


def compute_realization_audit(
    plan: SpecShipPlan,
    digest: Optional[SpecDigest],
    examiner_receipt: Optional[Dict[str, Any]],
) -> RealizationAudit:
    """Computes code-only file counts, expected vs. actual file diff, and AC/IC criteria matrix."""
    actual_code_files = _extract_actual_code_files(plan.matched_files)
    realized, untouched, unplanned = _classify_audit_files(plan, actual_code_files)
    file_tree_diff = _build_file_tree_diff(realized, unplanned, untouched)
    criteria_rows = _build_criteria_rows(digest, plan, examiner_receipt, actual_code_files, realized)
    return RealizationAudit(
        actual_code_files=actual_code_files,
        realized_files=realized,
        untouched_expected_files=untouched,
        unplanned_extra_files=unplanned,
        file_tree_diff=file_tree_diff,
        criteria_rows=criteria_rows,
    )
