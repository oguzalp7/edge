"""Ship-prep submodule: split_branches."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.models import SpecShipPlan
from tools.brigade.ship.paths import _norm_rel_path
from tools.brigade.ship.git_commits import _resolve_spec_commits
from tools.brigade.ship.split_materialize import _cherry_pick_slice_commits, _materialize_checkout_files

def _materialize_single_branch(
    repo: Path,
    eff_base: str,
    head_sha: str,
    head_tree: set,
    plan: SpecShipPlan,
    exclusive_commits: Optional[List[str]] = None,
    has_shared_commits: bool = False,
) -> Tuple[bool, str]:
    slice_shas = exclusive_commits if exclusive_commits is not None else plan.commit_shas
    if slice_shas and not has_shared_commits:
        return _cherry_pick_slice_commits(repo, plan.pr_branch, eff_base, slice_shas)
    return _materialize_checkout_files(repo, eff_base, head_sha, head_tree, plan)


def _prepare_split_branch_context(
    repo: Path,
) -> Tuple[bool, str, str, set, str]:
    st_code, st_out, _ = call_run_command(["git", "status", "--porcelain"], cwd=repo)
    if st_code != 0 or st_out.strip():
        return False, "", "", set(), "Working tree must be clean before running --split-branches."

    _, orig_branch, _ = call_run_command(["git", "branch", "--show-current"], cwd=repo)
    _, head_sha, _ = call_run_command(["git", "rev-parse", "HEAD"], cwd=repo)
    head_sha = head_sha.strip()
    orig_ref = orig_branch.strip() or head_sha

    ls_code, ls_out, ls_err = call_run_command(["git", "ls-tree", "-r", "--name-only", head_sha], cwd=repo)
    if ls_code != 0:
        return False, "", "", set(), f"Failed to inspect HEAD tree: {ls_err}"
    head_tree: set = set()
    for line in ls_out.splitlines():
        if line.strip():
            head_tree.add(_norm_rel_path(line))
    return True, head_sha, orig_ref, head_tree, ""


def create_split_branches(
    repo: Path,
    eff_base: str,
    spec_plans: List[SpecShipPlan],
    ticket_map: Optional[Dict[str, str]] = None,
) -> Tuple[bool, List[str], str]:
    """Creates isolated ship/<spec-slug> branches off eff_base, always restoring original HEAD."""
    if not spec_plans:
        return True, [], ""

    ctx_ok, head_sha, orig_ref, head_tree, ctx_err = _prepare_split_branch_context(repo)
    if not ctx_ok:
        return False, [], ctx_err
    exclusive, has_shared, _ = _resolve_spec_commits(repo, eff_base, spec_plans, ticket_map or {})

    created: List[str] = []
    try:
        for plan in spec_plans:
            ok, err = _materialize_single_branch(
                repo, eff_base, head_sha, head_tree, plan,
                exclusive_commits=exclusive.get(plan.pr_branch, []),
                has_shared_commits=has_shared.get(plan.pr_branch, False),
            )
            if not ok:
                return False, created, err
            created.append(plan.pr_branch)
    finally:
        call_run_command(["git", "checkout", orig_ref], cwd=repo)

    return True, created, ""
