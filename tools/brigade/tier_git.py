"""Git branch and working-tree cleanliness checks for Edge tier switching (stdlib-only)."""

from pathlib import Path
import sys
import subprocess
from typing import List, Optional, Tuple

from tools.brigade.tier_models import PRO_BRANCH, ULTRA_BRANCH


def run_git(args: List[str], cwd: Path) -> Tuple[int, str, str]:
    """Run a git command in cwd returning (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        return proc.returncode, proc.stdout.rstrip("\r\n"), proc.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def get_current_git_branch(repo: Path) -> str:
    """Return active git branch of repo or 'main' fallback."""
    code, out, _ = run_git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    return out.strip() if (code == 0 and out.strip()) else "main"


def _extract_dirty_path(line: str) -> Optional[str]:
    if len(line) < 3 or line.startswith("??"):
        return None
    path_part = line[2:].strip()
    if " -> " in path_part:
        path_part = path_part.split(" -> ")[1].strip()
    return None if path_part.startswith((".edge/", ".edge\\", ".edge")) else path_part


def check_tracked_cleanliness(repo: Path) -> Tuple[bool, List[str]]:
    """Return (is_clean, dirty_paths) for tracked modifications outside .edge/."""
    code, out, _ = run_git(["status", "--porcelain"], repo)
    if code != 0 or not out:
        return True, []
    dirty = [p for ln in out.splitlines() if (p := _extract_dirty_path(ln))]
    return len(dirty) == 0, dirty


def _ensure_branch_exists(repo: Path, branch: str) -> Tuple[bool, str]:
    code, _, _ = run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], repo)
    if code == 0:
        return True, ""
    create_code, _, create_err = run_git(["branch", branch], repo)
    return (True, "") if create_code == 0 else (False, f"Failed to create branch '{branch}': {create_err}")


def checkout_git_branch(repo: Path, branch: str) -> Tuple[bool, str]:
    """Check out requested git branch."""
    code, _, err = run_git(["checkout", branch], repo)
    return (True, "") if code == 0 else (False, f"Git checkout '{branch}' failed: {err}")


def resolve_switch_branch(repo: Path, tier_clean: str, checkout: bool) -> Tuple[bool, str, str]:
    """Resolve target branch for switch_tier; skip checkout unless checkout=True."""
    if not checkout:
        return True, get_current_git_branch(repo), ""
    is_clean, dirty_files = check_tracked_cleanliness(repo)
    if not is_clean:
        return False, "", f"Cannot switch tier: Working tree has uncommitted tracked changes outside .edge/ ({', '.join(dirty_files)})"
    target_branch = ULTRA_BRANCH if tier_clean == "ultra" else PRO_BRANCH
    if tier_clean == "ultra":
        ok, err = _ensure_branch_exists(repo, ULTRA_BRANCH)
        if not ok:
            return False, target_branch, err
    facade = sys.modules.get("tools.brigade.tier")
    co_fn = getattr(facade, "_checkout_git_branch", checkout_git_branch) if facade else checkout_git_branch
    ok, err = co_fn(repo, target_branch)
    return (True, target_branch, "") if ok else (False, target_branch, err)
