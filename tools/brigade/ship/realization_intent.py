"""Ship-prep submodule: realization_intent."""

from fnmatch import fnmatch
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json

from tools.brigade.ship.models import IndexChange, SpecDigest, SpecShipPlan
from tools.brigade.ship.paths import _norm_rel_path
from tools.brigade.ship.paths_spec import _is_broad_path, _is_critique_spec, _is_meta_spec_or_index, _matches_any_expected

def _resolve_intent_targets(
    head_branch: str,
    index_changes: List[IndexChange],
    changed_files: List[str],
) -> List[str]:
    targets = [
        f"{c.kind} {c.symbol}"
        for c in index_changes
        if c.kind in ("@route", "@module", "@spec") and not _is_critique_spec(c.symbol)
    ][:4]
    if targets:
        return targets
    clean_files = [f for f in changed_files if not _is_critique_spec(f)][:3]
    return clean_files or [head_branch or "HEAD"]


def _build_intent_str(
    head_branch: str,
    index_changes: List[IndexChange],
    verified_proofs: List[Dict[str, Any]],
    changed_files: List[str],
    spec_digests: Optional[List[SpecDigest]] = None,
) -> str:
    targets = _resolve_intent_targets(head_branch, index_changes, changed_files)
    spec_items = [f"{Path(d.path).stem}: {d.title}" for d in (spec_digests or [])[:6]]
    spec_part = f" | Specs: {'; '.join(spec_items)}" if spec_items else ""
    proof_slugs = [p["slug"] for p in verified_proofs]
    proof_part = f" | Verified QA proofs: {', '.join(proof_slugs)}" if proof_slugs else ""
    raw_intent = f"Deliver {head_branch or 'slice'} ({', '.join(targets)}){spec_part}{proof_part}"
    return " ".join(raw_intent.split())


def _build_scenario_contract(
    head_branch: str,
    index_changes: List[IndexChange],
    verified_proofs: List[Dict[str, Any]],
    examiner_receipt: Optional[Dict[str, Any]],
    changed_files: List[str],
) -> List[str]:
    contract: List[str] = [f"{c.kind}: {c.symbol}" for c in index_changes]
    for p in verified_proofs:
        acts = ", ".join(p.get("user_actions_executed", []))
        urls = ", ".join(p.get("visited_urls", []))
        contract.append(f"QA Proof [{p['slug']}]: actions=[{acts}] urls=[{urls}] db={json.dumps(p.get('db_crosscheck', {}))}")
    if examiner_receipt:
        contract.append(f"Examiner [{examiner_receipt.get('verdict')}]: {examiner_receipt.get('summary')}")
    if contract:
        return contract
    return [f"Changed: {f}" for f in changed_files[:8]] or [f"Branch: {head_branch}"]


def _append_unique_str(target: List[str], items: List[str]) -> None:
    for item in items:
        if item not in target:
            target.append(item)


def _classify_audit_files(
    plan: SpecShipPlan, actual_code_files: List[str]
) -> Tuple[List[str], List[str], List[str]]:
    realized: List[str] = []
    untouched: List[str] = []
    for raw_exp in plan.expected_files:
        pat = _norm_rel_path(raw_exp)
        hits = [f for f in actual_code_files if fnmatch(f, pat) or f == pat]
        if hits:
            _append_unique_str(realized, hits)
        elif not any(ch in pat for ch in "*?[") and not _is_broad_path(pat):
            _append_unique_str(untouched, [pat])
    unplanned = [
        f for f in actual_code_files
        if not _is_meta_spec_or_index(f, plan.spec_path) and not _matches_any_expected(f, plan.expected_files)
    ]
    return realized, untouched, unplanned


def _build_file_tree_diff(
    realized: List[str],
    unplanned: List[str],
    untouched: List[str],
) -> str:
    diff_lines = [f"+ {f} (expected)" for f in realized]
    diff_lines.extend(f"~ {f} (unplanned)" for f in unplanned)
    diff_lines.extend(f"! {f} (expected but untouched)" for f in untouched)
    if not diff_lines:
        return ""
    if len(diff_lines) > 30:
        extra = len(diff_lines) - 30
        diff_lines = [*diff_lines[:30], f"... (+{extra} more)"]
    return "```diff\n" + "\n".join(diff_lines) + "\n```"
