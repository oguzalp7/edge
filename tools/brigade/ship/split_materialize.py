"""Ship-prep submodule: split_materialize."""

from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

from tools.brigade.ship.models import call_run_command
from tools.brigade.ship.models import SpecShipPlan
from tools.brigade.ship.paths import _norm_rel_path
from tools.brigade.ship.git_commits import _collect_plan_tree_files

def _resolve_du_edge_conflicts(repo: Path, sha: str) -> bool:
    """Resolves modify/delete (DU) conflicts solely on .edge/ artifacts overwritten across slices."""
    _, st_out, _ = call_run_command(["git", "status", "--porcelain"], cwd=repo)
    du_edge: List[str] = []
    conflict_codes = {"UU", "AA", "DD", "DU", "UD", "AU", "UA"}
    for line in st_out.splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], _norm_rel_path(line[3:].strip().strip('"'))
        if code == "DU" and path.startswith(".edge/"):
            du_edge.append(path)
        elif code in conflict_codes:
            return False
    if not du_edge:
        return False
    cmds = (
        ["git", "checkout", sha, "--", *du_edge],
        ["git", "add", "--", *du_edge],
        ["git", "commit", "--no-edit"],
    )
    return all(call_run_command(c, cwd=repo)[0] == 0 for c in cmds)


def _cherry_pick_slice_commits(
    repo: Path,
    pr_branch: str,
    eff_base: str,
    commit_shas: List[str],
) -> Tuple[bool, str]:
    c_code, _, c_err = call_run_command(["git", "checkout", "-B", pr_branch, eff_base], cwd=repo)
    if c_code != 0:
        return False, f"Failed to create branch '{pr_branch}': {c_err}"
    for sha in commit_shas:
        cp_code, cp_out, cp_err = call_run_command(
            ["git", "cherry-pick", "-X", "theirs", sha],
            cwd=repo,
        )
        if cp_code == 0:
            continue
        combined = f"{cp_out}\n{cp_err}".lower()
        if "nothing to commit" in combined or "previous cherry-pick is now empty" in combined:
            call_run_command(["git", "cherry-pick", "--skip"], cwd=repo)
            continue
        if _resolve_du_edge_conflicts(repo, sha):
            continue
        call_run_command(["git", "cherry-pick", "--abort"], cwd=repo)
        return False, f"Failed to cherry-pick {sha[:8]} onto '{pr_branch}': {cp_err or cp_out}"
    return True, ""


def _materialize_checkout_files(
    repo: Path,
    eff_base: str,
    head_sha: str,
    head_tree: set,
    plan: SpecShipPlan,
) -> Tuple[bool, str]:
    c_code, _, c_err = call_run_command(["git", "checkout", "-B", plan.pr_branch, eff_base], cwd=repo)
    if c_code != 0:
        return False, f"Failed to create branch '{plan.pr_branch}': {c_err}"

    files = _collect_plan_tree_files(plan, head_tree)
    if not files:
        return True, ""

    co_code, _, co_err = call_run_command(["git", "checkout", head_sha, "--", *files], cwd=repo)
    if co_code != 0:
        return False, f"Failed to checkout slice files onto '{plan.pr_branch}': {co_err}"

    add_code, _, add_err = call_run_command(["git", "add", "--", *files], cwd=repo)
    if add_code != 0:
        return False, f"Failed to stage slice files on '{plan.pr_branch}': {add_err}"

    diff_code, _, _ = call_run_command(["git", "diff", "--cached", "--quiet"], cwd=repo)
    if diff_code != 0:
        cm_code, _, cm_err = call_run_command(["git", "commit", "-m", plan.pr_title], cwd=repo)
        if cm_code != 0:
            return False, f"Failed to commit '{plan.pr_branch}': {cm_err}"
    return True, ""
