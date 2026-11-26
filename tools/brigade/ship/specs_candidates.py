"""Ship-prep submodule: specs_candidates."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.paths import _clean_slug, _match_expected_files
from tools.brigade.ship.paths_spec import _is_broad_path, _is_valid_spec_candidate, _resolve_spec_on_disk, _spec_slug_from_rel
from tools.brigade.ship.spec_expected import _extract_spec_expected_files
from tools.brigade.ship.tickets_proofs import _receipt_matches_spec

def _list_disk_spec_candidates(repo: Path) -> List[str]:
    candidates: List[str] = []
    for base_rel in (".edge/specs", ".edge/archive/specs"):
        folder = repo / base_rel
        if not folder.is_dir():
            continue
        for md_file in sorted(folder.glob("*.md")):
            rel = f"{base_rel}/{md_file.name}"
            if _is_valid_spec_candidate(rel):
                candidates.append(rel)
    return candidates


def _ticket_anchored_for_spec(
    repo: Path,
    rel: str,
    spec_slug: str,
    log_body: str,
    tid: Optional[str],
    history_receipts: Dict[str, Dict[str, Any]],
) -> bool:
    if not tid or tid not in log_body:
        return False
    rec = history_receipts.get(tid)
    if rec and _receipt_matches_spec(rec, rel, spec_slug):
        return True
    spec_file = repo / rel
    return bool(spec_file.is_file() and tid in spec_file.read_text(encoding="utf-8", errors="ignore"))


def _spec_has_diff_anchor(
    repo: Path,
    rel: str,
    log_body: str,
    ticket_map: Dict[str, str],
    history_receipts: Dict[str, Dict[str, Any]],
    diff_proof_slugs: set,
) -> bool:
    spec_slug = _clean_slug(Path(rel).stem)
    if spec_slug and spec_slug in log_body.lower():
        return True
    if rel in log_body or spec_slug in diff_proof_slugs:
        return True
    return _ticket_anchored_for_spec(repo, rel, spec_slug, log_body, ticket_map.get(rel), history_receipts)


def _specific_matched_files(repo: Path, rel: str, changed_files: List[str]) -> List[str]:
    expected = _extract_spec_expected_files(repo / rel)
    specific: List[str] = []
    for pat in expected:
        if not _is_broad_path(pat, repo):
            specific.append(pat)
    return _match_expected_files(specific, changed_files) if specific else []


def _unanchored_spec_eligible(
    repo: Path,
    rel: str,
    changed_files: List[str],
    covered_files: set,
    base_ts: int,
    has_anchors: bool,
    diff_proof_slugs: set,
) -> bool:
    hits = _specific_matched_files(repo, rel, changed_files)
    if not hits:
        return False
    if not has_anchors:
        return True
    spec_file = repo / rel
    if rel.startswith(".edge/archive/specs/") and base_ts and int(spec_file.stat().st_mtime) < base_ts:
        return False
    spec_slug = _clean_slug(spec_file.stem)
    old_proof = repo / ".edge" / "qa" / "proofs" / f"{spec_slug}.json"
    if old_proof.is_file() and spec_slug not in diff_proof_slugs:
        return False
    return any(h not in covered_files for h in hits)


def _deduplicate_spec_candidates(repo: Path, candidates: List[str]) -> List[str]:
    by_slug: Dict[str, str] = {}
    for raw in candidates:
        if not _is_valid_spec_candidate(raw):
            continue
        resolved = _resolve_spec_on_disk(repo, raw)
        if not resolved:
            continue
        slug = _spec_slug_from_rel(resolved)
        if slug not in by_slug or resolved.startswith(".edge/archive/specs/"):
            by_slug[slug] = resolved
    return list(by_slug.values())
