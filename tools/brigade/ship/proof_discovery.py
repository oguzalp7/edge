"""Ship-prep submodule: proof_discovery."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.paths import _norm_rel_path
from tools.brigade.ship.proof_meta import _parse_proof_raw_meta

def _collect_diff_proof_paths(repo: Path, changed_files: List[str]) -> List[Path]:
    found: List[Path] = []
    for cf in changed_files:
        norm = _norm_rel_path(cf)
        is_proof = norm.startswith(".edge/qa/proofs/") and norm.endswith(".json")
        if is_proof and not norm.endswith("-visual.json"):
            cand = repo / norm
            if cand.is_file():
                found.append(cand)
    return found


def _filter_unique_proofs(candidates: List[Path], selected_slug: Optional[str]) -> List[Path]:
    unique: List[Path] = []
    seen_names: set = set()
    for pf in candidates:
        if pf.name not in seen_names:
            seen_names.add(pf.name)
            unique.append(pf)
    return unique


def _scan_dir_matching_proofs(
    proofs_dir: Path,
    slug_set: set,
    ticket_set: set,
    ticket_by_slug: Dict[str, Optional[str]],
) -> List[Path]:
    if not proofs_dir.is_dir():
        return []
    found: List[Path] = []
    for pf in sorted(proofs_dir.glob("*.json")):
        if pf.name.endswith("-visual.json"):
            continue
        meta = _parse_proof_raw_meta(pf.read_text(encoding="utf-8", errors="ignore"), pf.name, ticket_by_slug)
        if meta["spec_slug"] in slug_set or (meta["ticket_id"] and meta["ticket_id"] in ticket_set):
            found.append(pf)
    return found


def _collect_matching_disk_proofs(
    roots: List[Path],
    spec_slugs: List[str],
    ticket_by_slug: Dict[str, Optional[str]],
) -> List[Path]:
    slug_set = set(spec_slugs)
    ticket_set = {v for v in ticket_by_slug.values() if v}
    found: List[Path] = []
    for root in roots:
        found.extend(_scan_dir_matching_proofs(root / ".edge" / "qa" / "proofs", slug_set, ticket_set, ticket_by_slug))
    return found


def _discover_scoped_proof_files(
    repo: Path,
    roots: List[Path],
    spec_slugs: List[str],
    changed_files: List[str],
    selected_slug: Optional[str],
    ticket_by_slug: Optional[Dict[str, Optional[str]]] = None,
) -> List[Path]:
    """Collects ONLY proof files belonging to changed specs or changed in <base>..HEAD."""
    candidates: List[Path] = []
    for root in roots:
        for slug in spec_slugs:
            cand = root / ".edge" / "qa" / "proofs" / f"{slug}.json"
            if cand.is_file():
                candidates.append(cand)
    candidates.extend(_collect_diff_proof_paths(repo, changed_files))
    candidates.extend(_collect_matching_disk_proofs(roots, spec_slugs, ticket_by_slug or {}))
    return _filter_unique_proofs(candidates, selected_slug)


def _match_commit_proof_blobs(
    repo: Path,
    sha: str,
    spec_slug: str,
    ticket_id: Optional[str],
    ticket_by_slug: Dict[str, Optional[str]],
) -> List[Tuple[str, str]]:
    _, paths_out, _ = call_run_command(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha, "--", ".edge/qa/proofs/"],
        cwd=repo,
    )
    hits: List[Tuple[str, str]] = []
    for rel in paths_out.splitlines():
        norm = _norm_rel_path(rel)
        if not norm.endswith(".json") or norm.endswith("-visual.json"):
            continue
        b_code, raw_text, _ = call_run_command(["git", "show", f"{sha}:{norm}"], cwd=repo)
        if b_code != 0 or not raw_text.strip():
            continue
        meta = _parse_proof_raw_meta(raw_text, norm, ticket_by_slug)
        if meta["spec_slug"] == spec_slug or (ticket_id and meta["ticket_id"] == ticket_id):
            hits.append((norm, raw_text))
    return hits


def _discover_historical_proof_blobs(
    repo: Path,
    eff_base: str,
    spec_slug: str,
    ticket_id: Optional[str],
    ticket_by_slug: Optional[Dict[str, Optional[str]]] = None,
) -> List[Tuple[str, str]]:
    """Recovers historical proof JSON blobs in eff_base..HEAD matching spec_slug or ticket_id."""
    code, log_out, _ = call_run_command(
        ["git", "log", "--format=%H", f"{eff_base}..HEAD", "--", ".edge/qa/proofs/"],
        cwd=repo,
    )
    if code != 0 or not log_out.strip():
        return []
    t_map = ticket_by_slug or {}
    for sha in log_out.splitlines():
        if not sha.strip():
            continue
        hits = _match_commit_proof_blobs(repo, sha.strip(), spec_slug, ticket_id, t_map)
        if hits:
            return hits
    return []
