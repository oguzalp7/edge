"""Machine-Generated 4-Seal RefactorReceipt & Deterministic Verifier Facade."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tools.brigade.receipt_git import (
    build_seal_4_from_examiner,
    get_diff_changed_files,
    get_git_head_sha,
    load_ticket_frontmatter,
    run_git,
)
from tools.brigade.receipt_models import (
    HIGHER_IS_BETTER_METRICS,
    LOWER_IS_BETTER_METRICS,
    RefactorReceipt,
    compute_changed_files_hash,
    compute_neutrality,
    norm_rel,
)
from tools.brigade.receipt_verifier import RefactorReceiptVerifier
from tools.common import normalize_target_path

try:
    from .tasks_bridge import resolve_target_repo_root
except ImportError:
    from tools.brigade.tasks_bridge import resolve_target_repo_root


def _resolve_ticket_targets(fm: Dict[str, Any], ticket: Any) -> Tuple[List[str], List[str], Dict[str, Any], Any]:
    target_rules = list(fm.get("target_rules") or ([ticket.rule_id] if ticket and ticket.rule_id else []))
    fallback_files = [ticket.target_file] if ticket and ticket.target_file else []
    target_files = list(fm.get("target_files") or (getattr(ticket, "expected_files", None) or fallback_files))
    metric_targets = dict((getattr(ticket, "metric_targets", None) or {}) if ticket else {})
    if not metric_targets and isinstance(fm.get("metric_targets"), dict):
        metric_targets = dict(fm["metric_targets"])
    tasks_axi_id = (getattr(ticket, "tasks_axi_id", None) if ticket else None) or fm.get("tasks_axi_id")
    return target_rules, target_files, metric_targets, tasks_axi_id


def build_and_write_refactor_receipt(
    target_repo: Path, work_dir: Path, slug: str, base_branch: str,
    ticket: Any = None, examiner_receipt: Any = None, surgeon_cid: Optional[str] = None,
) -> Tuple[RefactorReceipt, Path, Path]:
    """Run EdgeVerificationGate, classify door risk, synthesize 4 seals, and atomically write receipt."""
    from tools.brigade.ship_prep import classify_merge_danger
    from tools.gate import EdgeVerificationGate

    root_repo = resolve_target_repo_root(target_repo)
    eff_work_dir = normalize_target_path(work_dir)
    track = getattr(ticket, "track", "core") if ticket else "core"
    ticket_id = getattr(ticket, "ticket_id", f"TICK-{track.upper()[:4]}-{slug.upper()}") if ticket else f"TICK-{track.upper()[:4]}-{slug.upper()}"
    fm, ticket_rel_path = load_ticket_frontmatter(root_repo, slug, getattr(ticket, "refactor_ticket_path", None) if ticket else None)
    gate_payload = EdgeVerificationGate(eff_work_dir).run_all_structured(base_ref=base_branch, is_refactor=True, skip_verification=True, track=track)
    commit_sha = gate_payload.get("commit_sha") or get_git_head_sha(eff_work_dir)
    changed_files = get_diff_changed_files(eff_work_dir, base_branch)
    if not changed_files and ticket and getattr(ticket, "target_file", ""):
        changed_files = [norm_rel(ticket.target_file)]
    _, diff_stat, _ = run_git(eff_work_dir, ["diff", "--stat", f"{base_branch}..HEAD"])
    _, diff_text, _ = run_git(eff_work_dir, ["diff", f"{base_branch}..HEAD"])
    door_type, blast_radius = classify_merge_danger(changed_files, diff_stat=diff_stat, diff_text=diff_text, is_refactor=True)
    target_rules, target_files, metric_targets, tasks_axi_id = _resolve_ticket_targets(fm, ticket)
    eff_surgeon_cid = surgeon_cid or (getattr(ticket, "surgeon_cid", None) if ticket else None)
    receipt = RefactorReceipt(
        slug=slug, ticket_id=ticket_id, track=track,
        seal_1_intent={
            "ticket_id": ticket_id, "slug": slug, "track": track, "target_rules": target_rules, "target_files": target_files,
            "changed_files": list(changed_files), "changed_files_hash": compute_changed_files_hash(changed_files),
            "commit_sha": commit_sha, "behavior_preserved": True, "door_type": door_type,
            "one_way_reasons": list(blast_radius.get("one_way_reasons") or []), "ticket_path": ticket_rel_path, "tasks_axi_id": tasks_axi_id,
        },
        seal_2_metrics={"before": dict(getattr(ticket, "before_metrics", None) or {}) if ticket else {}, "after": dict(gate_payload.get("metrics") or {}), "metric_targets": metric_targets},
        seal_3_gate={"all_passed": bool(gate_payload.get("all_passed")), "stages": list(gate_payload.get("stages") or []), "commit_sha": commit_sha, "base_branch": base_branch, "track": track},
        seal_4_examiner=build_seal_4_from_examiner(examiner_receipt, eff_surgeon_cid, changed_files),
    )
    json_path, md_path = receipt.write(root_repo)
    return receipt, json_path, md_path


def refresh_receipt_examiner_seal(
    target_repo: Path, slug: str, examiner_receipt: Any, surgeon_cid: Optional[str] = None,
) -> Optional[Tuple[RefactorReceipt, Path, Path]]:
    """Refresh Seal 4 of an existing RefactorReceipt with the sealed ExaminerReceipt."""
    root_repo = resolve_target_repo_root(target_repo)
    json_path = root_repo / ".edge" / "receipts" / "refactor" / f"{slug}.json"
    if not json_path.is_file():
        return None
    try:
        receipt = RefactorReceipt.from_dict(json.loads(json_path.read_text(encoding="utf-8")))
    except Exception:
        return None
    eff_surgeon = surgeon_cid or receipt.seal_4_examiner.get("surgeon_cid")
    receipt.seal_4_examiner = build_seal_4_from_examiner(examiner_receipt, eff_surgeon, list(receipt.seal_1_intent.get("changed_files") or []))
    j_path, m_path = receipt.write(root_repo)
    return receipt, j_path, m_path
