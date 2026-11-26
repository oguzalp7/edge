"""Ship-prep submodule: git_commits."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
import re

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.models import SpecShipPlan
from tools.brigade.ship.paths import _match_expected_files, _norm_rel_path
from tools.brigade.ship.paths_spec import _is_broad_path

def _collect_plan_tree_files(plan: SpecShipPlan, head_tree: set) -> List[str]:
    candidates: List[str] = [*plan.matched_files, plan.spec_path]
    proof_rel = f".edge/qa/proofs/{plan.spec_slug}.json"
    candidates.append(proof_rel)
    for vp in plan.verified_proofs:
        if vp.get("path"):
            candidates.append(_norm_rel_path(vp["path"]))
        candidates.extend(_norm_rel_path(str(s)) for s in vp.get("screenshot_paths", []))
    ordered: List[str] = []
    for c in candidates:
        norm = _norm_rel_path(c)
        if norm in head_tree and norm not in ordered:
            ordered.append(norm)
    return ordered


def _list_range_commits(repo: Path, eff_base: str) -> List[Tuple[str, str, List[str]]]:
    code, out, _ = call_run_command(["git", "log", "--reverse", "--format=%H%x00%B%x1e", f"{eff_base}..HEAD"], cwd=repo)
    if code != 0 or not out.strip():
        return []
    commits: List[Tuple[str, str, List[str]]] = []
    for record in out.split("\x1e"):
        if "\x00" not in record:
            continue
        sha, msg = record.split("\x00", 1)
        sha = sha.strip()
        if not sha:
            continue
        _, f_out, _ = call_run_command(
            ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
            cwd=repo,
        )
        c_files = [_norm_rel_path(f) for f in f_out.splitlines() if f.strip()]
        commits.append((sha, msg.strip(), c_files))
    return commits


def _ticket_commit_owners(
    message: str,
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
) -> List[str]:
    owners: List[str] = []
    for p in plans:
        tid = p.ticket_id or ticket_map.get(p.spec_path)
        if tid and re.search(rf"(?<![A-Za-z0-9-]){re.escape(tid)}(?![A-Za-z0-9-])", message):
            owners.append(p.pr_branch)
    return owners


def _explicit_commit_owners(
    subject: str,
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
) -> List[str]:
    tid_owners = _ticket_commit_owners(subject, plans, ticket_map)
    if tid_owners:
        return tid_owners
    low_subj = subject.lower()
    owners: List[str] = []
    for p in plans:
        slug_hit = bool(re.search(rf"(?<![a-z0-9-]){re.escape(p.spec_slug)}(?![a-z0-9-])", low_subj))
        if slug_hit:
            owners.append(p.pr_branch)
    return owners


def _overlap_commit_owners(c_files: List[str], plans: List[SpecShipPlan]) -> List[str]:
    owners: List[str] = []
    for p in plans:
        specific = [pat for pat in p.expected_files if not _is_broad_path(pat)]
        if specific and _match_expected_files(specific, c_files):
            owners.append(p.pr_branch)
    return owners


def _match_commit_owners(
    subject: str,
    c_files: List[str],
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
    last_owner: Optional[str],
) -> List[str]:
    tid_owners = _ticket_commit_owners(subject, plans, ticket_map)
    if tid_owners:
        return tid_owners
    overlap = _overlap_commit_owners(c_files, plans)
    if overlap:
        return overlap
    explicit = _explicit_commit_owners(subject, plans, ticket_map)
    if explicit:
        return explicit
    if last_owner:
        return [last_owner]
    return [plans[0].pr_branch] if len(plans) == 1 else []


def _resolve_spec_commits(
    repo: Path,
    eff_base: str,
    plans: List[SpecShipPlan],
    ticket_map: Dict[str, str],
) -> Tuple[Dict[str, List[str]], Dict[str, bool], Dict[str, List[str]]]:
    """Attributes eff_base..HEAD commits per plan (ticket/file overlap/slug/contiguous)."""
    exclusive: Dict[str, List[str]] = {p.pr_branch: [] for p in plans}
    has_shared: Dict[str, bool] = {p.pr_branch: False for p in plans}
    exc_files: Dict[str, List[str]] = {p.pr_branch: [] for p in plans}
    last_owner: Optional[str] = None
    for sha, subj, c_files in _list_range_commits(repo, eff_base):
        owners = _match_commit_owners(subj, c_files, plans, ticket_map, last_owner)
        if len(owners) == 1:
            owner_key = owners[0]
            exclusive[owner_key].append(sha)
            exc_files[owner_key].extend(f for f in c_files if f not in exc_files[owner_key])
            last_owner = owner_key
        else:
            for owner_key in owners:
                has_shared[owner_key] = True
            last_owner = None
    return exclusive, has_shared, exc_files
