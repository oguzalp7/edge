"""Ship-prep submodule: plans_refactor."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import json

from tools.brigade.refactor_receipt import RefactorReceiptVerifier, compute_changed_files_hash
from tools.brigade.ship.models import call_run_command
from tools.brigade.tasks_bridge import resolve_target_repo_root
from tools.brigade.ship.models import IndexChange, SpecShipPlan
from tools.brigade.ship.paths import _clean_slug, _filter_plan_index_changes, _match_expected_files, _norm_rel_path
from tools.brigade.ship.render_markdown import _render_plan_bodies
from tools.brigade.ship.plans import _clean_pr_title

def _discover_refactor_receipts(
    repo: Path,
    changed_files: List[str],
) -> List[Tuple[str, Dict[str, Any]]]:
    """Discovers valid (non-stale) refactor receipts pinned under target_repo/.edge/receipts/refactor/."""
    roots = [resolve_target_repo_root(repo)]
    if repo not in roots:
        roots.append(repo)

    _, head_out, _ = call_run_command(["git", "rev-parse", "HEAD"], cwd=repo)
    head_sha = head_out.strip()
    cur_diff_hash = compute_changed_files_hash(changed_files) if changed_files else ""

    discovered: List[Tuple[str, Dict[str, Any]]] = []
    seen_slugs: set = set()
    for root in roots:
        rec_dir = root / ".edge" / "receipts" / "refactor"
        if not rec_dir.is_dir():
            continue
        for json_file in sorted(rec_dir.glob("*.json")):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            s1 = data.get("seal_1_intent")
            if not isinstance(s1, dict):
                continue
            rec_sha = str(s1.get("commit_sha") or "").strip()
            rec_hash = str(s1.get("changed_files_hash") or "").strip()
            if not ((head_sha and rec_sha == head_sha) or (cur_diff_hash and rec_hash == cur_diff_hash)):
                continue
            slug = _clean_slug(str(data.get("slug") or s1.get("slug") or json_file.stem))
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            discovered.append((f".edge/receipts/refactor/{json_file.name}", data))
    return discovered


def _build_single_refactor_plan(
    rel_path: str, rec: Dict[str, Any], base_branch: str, changed_files: List[str],
    index_changes: List[IndexChange], context_terms: List[str], gate_status: str,
    used_branches: set, door_type: str, blast_radius: Dict[str, Any],
) -> SpecShipPlan:
    s1 = rec.get("seal_1_intent") or {}
    slug = _clean_slug(str(rec.get("slug") or s1.get("slug") or Path(rel_path).stem))
    tid = str(rec.get("ticket_id") or s1.get("ticket_id") or "") or None
    rec_files = [_norm_rel_path(f) for f in (s1.get("changed_files") or []) if str(f).strip()]
    target_files = [_norm_rel_path(f) for f in (s1.get("target_files") or []) if str(f).strip()]
    expected = list(dict.fromkeys([*rec_files, *target_files]))
    matched = _match_expected_files(expected, changed_files) or list(rec_files)
    cand_branch = f"ship/{slug}" if f"ship/{slug}" not in used_branches else f"ship/refactor-{slug}"
    used_branches.add(cand_branch)
    rules = [str(r) for r in (s1.get("target_rules") or []) if str(r).strip()]
    raw_title = f"refactor {', '.join(rules)}" if rules else f"clean {slug}"
    plan = SpecShipPlan(
        spec_slug=slug, spec_path=rel_path, pr_branch=cand_branch,
        pr_title=_clean_pr_title(slug, raw_title, kind="refactor"),
        expected_files=expected, matched_files=matched,
        index_changes=_filter_plan_index_changes(index_changes, slug, rel_path, matched),
        ticket_id=tid, kind="refactor", refactor_receipt=rec,
    )
    eff_door = str(s1.get("door_type") or door_type)
    eff_blast = dict(blast_radius)
    if s1.get("one_way_reasons"):
        eff_blast["one_way_reasons"] = list(dict.fromkeys([*(eff_blast.get("one_way_reasons") or []), *(s1.get("one_way_reasons") or [])]))
    _render_plan_bodies(plan, base_branch, context_terms, rec.get("seal_4_examiner") or None, gate_status, door_type=eff_door, blast_radius=eff_blast)
    return plan


def _build_refactor_plans(
    refactor_receipts: List[Tuple[str, Dict[str, Any]]], base_branch: str, changed_files: List[str],
    index_changes: List[IndexChange], context_terms: List[str], gate_status: str,
    used_branches: set, door_type: str, blast_radius: Dict[str, Any],
) -> List[SpecShipPlan]:
    return [
        _build_single_refactor_plan(
            rel_path, rec, base_branch, changed_files, index_changes,
            context_terms, gate_status, used_branches, door_type, blast_radius,
        )
        for rel_path, rec in refactor_receipts
    ]


def _select_spec_plans(
    plans: List[SpecShipPlan],
    spec_slug: Optional[str],
    eff_base: str,
) -> Tuple[bool, List[SpecShipPlan], Optional[str], str]:
    if not spec_slug:
        return True, plans, None, ""
    target = _clean_slug(spec_slug)
    matched = [p for p in plans if p.spec_slug == target]
    if not matched:
        return False, plans, target, f"Spec '{spec_slug}' not found among changed specs in {eff_base}..HEAD."
    return True, matched, target, ""
