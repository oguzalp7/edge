"""Ship-prep submodule: git_branches."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.models import IndexChange, SpecShipPlan
from tools.brigade.ship.paths import _filter_plan_index_changes, _is_evidence_artifact_path, _norm_rel_path

def _apply_slice_commits_to_plans(
    plans: List[SpecShipPlan],
    exclusive: Dict[str, List[str]],
    has_shared: Dict[str, bool],
    exc_files: Dict[str, List[str]],
    index_changes: List[IndexChange],
) -> None:
    for plan in plans:
        key = plan.pr_branch
        if not has_shared.get(key):
            plan.commit_shas = list(exclusive.get(key, []))
        for cf in exc_files.get(key, []):
            if not cf.startswith(".edge/") and cf not in plan.matched_files:
                plan.matched_files.append(cf)
        plan.index_changes = _filter_plan_index_changes(
            index_changes, plan.spec_slug, plan.spec_path, plan.matched_files
        )


def _read_existing_ship_branch_files(
    repo: Path,
    eff_base: str,
    pr_branch: str,
) -> Optional[List[str]]:
    rc, _, _ = call_run_command(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{pr_branch}"],
        cwd=repo,
    )
    if rc != 0:
        return None
    d_rc, d_out, _ = call_run_command(
        ["git", "diff", "--name-only", f"{eff_base}..{pr_branch}"],
        cwd=repo,
    )
    if d_rc != 0 or not d_out.strip():
        return None
    return [_norm_rel_path(line) for line in d_out.splitlines() if line.strip()]


def _merge_branch_code_files(matched_files: List[str], branch_files: List[str]) -> List[str]:
    meta = [
        _norm_rel_path(p) for p in matched_files
        if _norm_rel_path(p).startswith(".edge/") and not _is_evidence_artifact_path(p)
    ]
    code = [
        bf for bf in branch_files
        if not bf.startswith(".edge/") and not _is_evidence_artifact_path(bf)
    ]
    return list(dict.fromkeys([*meta, *code]))


def _scope_plans_to_existing_ship_branches(
    repo: Path,
    eff_base: str,
    plans: List[SpecShipPlan],
    index_changes: List[IndexChange],
) -> None:
    for plan in plans:
        branch_files = _read_existing_ship_branch_files(repo, eff_base, plan.pr_branch)
        if not branch_files:
            continue
        plan.matched_files = _merge_branch_code_files(plan.matched_files, branch_files)
        plan.index_changes = _filter_plan_index_changes(
            index_changes, plan.spec_slug, plan.spec_path, plan.matched_files
        )
