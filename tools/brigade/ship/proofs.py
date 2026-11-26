"""Ship-prep submodule: proofs."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.models import BrigadeState, Ticket
from tools.brigade.ship.proof_meta import _proof_search_roots, _verify_proof_raw_text
from tools.brigade.ship.proof_discovery import _discover_historical_proof_blobs, _discover_scoped_proof_files

def _proof_matches_selected(
    entry: Dict[str, Any],
    selected_slug: Optional[str],
    t_map: Dict[str, Optional[str]],
) -> bool:
    if not selected_slug:
        return True
    if entry.get("spec_slug") == selected_slug or entry.get("slug") == selected_slug:
        return True
    sel_tid = t_map.get(selected_slug)
    return bool(sel_tid and entry.get("ticket_id") == sel_tid)


def _verify_disk_proofs(
    repo: Path,
    roots: List[Path],
    ticket: Optional[Ticket],
    proof_files: List[Path],
    selected_slug: Optional[str],
    t_map: Dict[str, Optional[str]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    verified: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    for pf in proof_files:
        rel = str(pf.relative_to(repo)).replace("\\", "/") if repo in pf.parents else str(pf)
        raw_text = pf.read_text(encoding="utf-8", errors="ignore")
        ok, entry = _verify_proof_raw_text(raw_text, rel, roots, ticket, t_map)
        if not _proof_matches_selected(entry, selected_slug, t_map):
            continue
        (verified if ok else failed).append(entry)
    return verified, failed


def _proof_dedup_key(entry: Dict[str, Any]) -> Tuple[Any, ...]:
    hashes = tuple(sorted((entry.get("screenshot_hashes") or {}).values()))
    return (entry.get("path"), entry.get("spec_slug"), entry.get("ticket_id"), hashes)


def _append_unique_proof(
    ok: bool,
    entry: Dict[str, Any],
    verified: List[Dict[str, Any]],
    failed: List[Dict[str, Any]],
    seen_keys: set,
) -> None:
    key = _proof_dedup_key(entry)
    if key in seen_keys:
        return
    seen_keys.add(key)
    (verified if ok else failed).append(entry)


def _verify_historical_proofs_for_slugs(
    repo: Path,
    eff_base: str,
    roots: List[Path],
    ticket: Optional[Ticket],
    target_slugs: List[str],
    t_map: Dict[str, Optional[str]],
    verified: List[Dict[str, Any]],
    failed: List[Dict[str, Any]],
    seen_keys: set,
) -> None:
    covered_slugs = {e.get("spec_slug") for e in verified}
    for slug in target_slugs:
        if not slug or slug in covered_slugs:
            continue
        for rel_path, raw_text in _discover_historical_proof_blobs(repo, eff_base, slug, t_map.get(slug), t_map):
            ok, entry = _verify_proof_raw_text(raw_text, rel_path, roots, ticket, t_map)
            _append_unique_proof(ok, entry, verified, failed, seen_keys)
            covered_slugs.add(slug)


def _verify_scoped_proofs(
    repo: Path,
    ticket: Optional[Ticket],
    spec_slugs: List[str],
    changed_files: List[str],
    selected_slug: Optional[str] = None,
    eff_base: Optional[str] = None,
    ticket_by_slug: Optional[Dict[str, Optional[str]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    roots = _proof_search_roots(repo, ticket)
    t_map = ticket_by_slug or {}
    proof_files = _discover_scoped_proof_files(repo, roots, spec_slugs, changed_files, selected_slug, ticket_by_slug=t_map)
    raw_v, raw_f = _verify_disk_proofs(repo, roots, ticket, proof_files, selected_slug, t_map)
    verified: List[Dict[str, Any]] = []
    failed: List[Dict[str, Any]] = []
    seen_keys: set = set()
    for e in raw_v:
        _append_unique_proof(True, e, verified, failed, seen_keys)
    for e in raw_f:
        _append_unique_proof(False, e, verified, failed, seen_keys)
    if not eff_base:
        return verified, failed

    target_slugs = [selected_slug] if selected_slug else list(spec_slugs)
    _verify_historical_proofs_for_slugs(
        repo, eff_base, roots, ticket, target_slugs, t_map, verified, failed, seen_keys
    )
    return verified, failed
