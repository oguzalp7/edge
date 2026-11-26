"""Ship-prep submodule: tickets."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.constants import _TICKET_RE
from tools.brigade.ship.paths import _match_expected_files, _norm_rel_path
from tools.brigade.ship.paths_spec import _is_broad_path, _resolve_spec_file_path, _spec_slug_from_rel
from tools.brigade.ship.topology_config import _base_commit_timestamp
from tools.brigade.ship.spec_expected import _extract_spec_expected_files
from tools.brigade.ship.tickets_proofs import _collect_proof_ticket_map, _receipt_matches_spec

def _commit_ticket_file_index(repo: Path, eff_base: str) -> List[Tuple[str, List[str]]]:
    code, out, _ = call_run_command(["git", "log", "--format=%H%x00%s", f"{eff_base}..HEAD"], cwd=repo)
    if code != 0 or not out.strip():
        return []
    entries: List[Tuple[str, List[str]]] = []
    for line in out.splitlines():
        if "\x00" not in line:
            continue
        sha, subj = line.split("\x00", 1)
        m = _TICKET_RE.search(subj)
        if not m:
            continue
        _, files_out, _ = call_run_command(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
            cwd=repo,
        )
        entries.append((m.group(1), [_norm_rel_path(f) for f in files_out.splitlines() if f.strip()]))
    return entries


def _match_commit_ticket_for_spec(
    spec_file: Path,
    commit_tickets: List[Tuple[str, List[str]]],
    bound_tids: set,
    repo: Path,
) -> Optional[str]:
    expected = [p for p in _extract_spec_expected_files(spec_file) if not _is_broad_path(p, repo)]
    if not expected:
        return None
    for tid, c_files in commit_tickets:
        if tid in bound_tids:
            continue
        if _match_expected_files(expected, c_files):
            return tid
    return None


def _resolve_explicit_spec_ticket(
    repo: Path,
    spec_rel: str,
    proof_tickets: Dict[str, str],
    history_receipts: Dict[str, Dict[str, Any]],
) -> Optional[str]:
    spec_file = _resolve_spec_file_path(repo, spec_rel)
    spec_slug = _spec_slug_from_rel(spec_rel)
    if spec_slug in proof_tickets:
        return proof_tickets[spec_slug]
    for tid, rec in history_receipts.items():
        if _receipt_matches_spec(rec, spec_rel, spec_slug):
            return tid
    if spec_file.is_file():
        m = _TICKET_RE.search(spec_file.read_text(encoding="utf-8", errors="ignore"))
        if m:
            return m.group(1)
    return None


def _resolve_spec_ticket_ids(
    repo: Path,
    eff_base: str,
    spec_paths: List[str],
    history_receipts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """Reverse-resolves TICK-* IDs (explicit anchors first, then unbound commit file overlap)."""
    if not spec_paths:
        return {}
    base_ts = _base_commit_timestamp(repo, eff_base)
    proof_tickets = _collect_proof_ticket_map(repo, eff_base, base_ts=base_ts)
    hist = history_receipts or {}
    resolved: Dict[str, str] = {}
    unresolved: List[str] = []
    for spec_rel in spec_paths:
        tid = _resolve_explicit_spec_ticket(repo, spec_rel, proof_tickets, hist)
        if tid:
            resolved[spec_rel] = tid
        else:
            unresolved.append(spec_rel)
    if unresolved:
        commit_tickets = _commit_ticket_file_index(repo, eff_base)
        bound_tids = set(resolved.values())
        for spec_rel in unresolved:
            tid = _match_commit_ticket_for_spec(_resolve_spec_file_path(repo, spec_rel), commit_tickets, bound_tids, repo)
            if tid:
                resolved[spec_rel] = tid
    return resolved
