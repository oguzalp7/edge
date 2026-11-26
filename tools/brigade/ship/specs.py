"""Ship-prep submodule: specs."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.models import IndexChange
from tools.brigade.ship.paths_spec import _is_valid_spec_candidate
from tools.brigade.ship.topology_config import _base_commit_timestamp
from tools.brigade.ship.brigade_snapshot import _load_brigade_history_snapshot
from tools.brigade.ship.tickets_proofs import _collect_diff_proof_slugs
from tools.brigade.ship.tickets import _resolve_spec_ticket_ids
from tools.brigade.ship.specs_candidates import _deduplicate_spec_candidates, _list_disk_spec_candidates, _spec_has_diff_anchor, _specific_matched_files, _unanchored_spec_eligible

def _scan_disk_specs_for_diff(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    ticket_map: Dict[str, str],
    history_receipts: Optional[Dict[str, Dict[str, Any]]] = None,
    has_git_specs: bool = False,
) -> List[str]:
    """Scans gitignored .edge specs on disk (anchored specs first, bounded unanchored fallback)."""
    _, log_body, _ = call_run_command(["git", "log", "--format=%B", f"{eff_base}..HEAD"], cwd=repo)
    hist = history_receipts or {}
    base_ts = _base_commit_timestamp(repo, eff_base)
    diff_proof_slugs = _collect_diff_proof_slugs(repo, eff_base, changed_files, base_ts)
    all_candidates = _list_disk_spec_candidates(repo)

    anchored: List[str] = []
    unanchored: List[str] = []
    for rel in all_candidates:
        if _spec_has_diff_anchor(repo, rel, log_body, ticket_map, hist, diff_proof_slugs):
            anchored.append(rel)
        else:
            unanchored.append(rel)

    covered_files: set = set()
    for rel in anchored:
        covered_files.update(_specific_matched_files(repo, rel, changed_files))

    has_anchors = bool(anchored or has_git_specs)
    matched = list(anchored)
    for rel in unanchored:
        if _unanchored_spec_eligible(repo, rel, changed_files, covered_files, base_ts, has_anchors, diff_proof_slugs):
            matched.append(rel)
    return matched


def discover_changed_specs(
    repo: Path,
    eff_base: str,
    changed_files: List[str],
    index_changes: List[IndexChange],
    ticket_map: Optional[Dict[str, str]] = None,
    history_receipts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[str]:
    """Discovers changed specs between eff_base..HEAD (git diff + gitignored .edge specs), deduplicated by slug."""
    _, spec_diff_out, _ = call_run_command(
        ["git", "diff", "--name-only", f"{eff_base}..HEAD", "--", ".edge/specs/", ".edge/archive/specs/"],
        cwd=repo,
    )
    git_specs = [line.strip() for line in spec_diff_out.splitlines() if line.strip() and _is_valid_spec_candidate(line)]
    candidates: List[str] = [*git_specs, *changed_files]
    candidates.extend(ch.symbol for ch in index_changes if ch.kind == "@spec")

    eff_hist = history_receipts if history_receipts is not None else _load_brigade_history_snapshot(repo)[3]
    disk_specs = _list_disk_spec_candidates(repo)
    eff_tickets = ticket_map if ticket_map is not None else _resolve_spec_ticket_ids(repo, eff_base, disk_specs, eff_hist)
    candidates.extend(
        _scan_disk_specs_for_diff(repo, eff_base, changed_files, eff_tickets, eff_hist, has_git_specs=bool(git_specs))
    )
    return _deduplicate_spec_candidates(repo, candidates)
