"""Ship-prep submodule: tickets_proofs."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.paths import _clean_slug, _norm_rel_path
from tools.brigade.ship.proof_meta import _extract_spec_slug_from_proof_json, _extract_ticket_from_proof_json

def _read_commit_proof_tickets(repo: Path, sha: str) -> Dict[str, str]:
    found: Dict[str, str] = {}
    _, paths_out, _ = call_run_command(
        ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha, "--", ".edge/qa/proofs/"],
        cwd=repo,
    )
    for rel in paths_out.splitlines():
        norm = _norm_rel_path(rel)
        if not norm.endswith(".json") or norm.endswith("-visual.json"):
            continue
        code, blob, _ = call_run_command(["git", "show", f"{sha}:{norm}"], cwd=repo)
        if code == 0 and blob:
            parsed = _extract_ticket_from_proof_json(blob)
            if parsed:
                found[parsed[0]] = parsed[1]
    return found


def _collect_proof_ticket_map(repo: Path, eff_base: str, base_ts: int = 0) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    code, log_out, _ = call_run_command(
        ["git", "log", "--reverse", "--format=%H", f"{eff_base}..HEAD", "--", ".edge/qa/proofs/"],
        cwd=repo,
    )
    if code == 0:
        for sha in log_out.splitlines():
            if sha.strip():
                mapping.update(_read_commit_proof_tickets(repo, sha.strip()))
    proofs_dir = repo / ".edge" / "qa" / "proofs"
    if proofs_dir.is_dir():
        for pf in sorted(proofs_dir.glob("*.json")):
            if pf.name.endswith("-visual.json"):
                continue
            if base_ts and int(pf.stat().st_mtime) < base_ts:
                continue
            parsed = _extract_ticket_from_proof_json(pf.read_text(encoding="utf-8", errors="ignore"))
            if parsed:
                mapping[parsed[0]] = parsed[1]
    return mapping


def _collect_diff_proof_slugs(
    repo: Path, eff_base: str, changed_files: List[str], base_ts: int
) -> set:
    slugs = set(_collect_proof_ticket_map(repo, eff_base, base_ts=base_ts).keys())
    for cf in changed_files:
        norm = _norm_rel_path(cf)
        if not (norm.startswith(".edge/qa/proofs/") and norm.endswith(".json") and not norm.endswith("-visual.json")):
            continue
        pf = repo / norm
        if not pf.is_file():
            continue
        if (slug := _extract_spec_slug_from_proof_json(pf.read_text(encoding="utf-8", errors="ignore"))):
            slugs.add(slug)
    return slugs


def _receipt_matches_spec(rec: Dict[str, Any], spec_rel: str, spec_slug: str) -> bool:
    target_name = Path(spec_rel).name.lower()
    for ev in rec.get("evidence_reviewed", []) or []:
        norm_ev = _norm_rel_path(str(ev))
        if norm_ev == spec_rel or norm_ev.lower().endswith(f"/{target_name}"):
            return True
        if _clean_slug(Path(norm_ev).stem) == spec_slug:
            return True
    return False
