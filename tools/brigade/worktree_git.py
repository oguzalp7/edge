"""
Native Git Worktree Backend for Edge Brigade.
@intent Manage isolated git worktree allocation, return, zero-loss branch cleanup, and orphan pruning outside repo root
@concepts native-worktree-fallback, zero-touch-worktree, cross-os-runtime-env
@invariants [INV-BRIGADE-ZERO-TOUCH-TREE], [INV-BRIGADE-WORKTREE-CLEANUP], [INV-BRIGADE-CROSS-OS-ENV]
"""

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import shutil
from typing import Callable, Dict, List, Optional, Set, Tuple

from tools.common import normalize_target_path, run_command
from tools.common.env import get_edge_home

RunnerFn = Callable[..., Tuple[int, str, str]]
_PROTECTED_BRANCHES = frozenset({"", "main", "master", "development", "staging"})


def sanitize_branch_dir(branch_name: str) -> str:
    """Convert a git branch name into a safe single directory component."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", branch_name.strip()).strip("-")
    return cleaned or "slice"


def get_repo_pool_root(repo_path: Path) -> Path:
    """Return the outside-repo native worktree pool root for a target repository."""
    norm_repo = normalize_target_path(repo_path)
    sha1 = hashlib.sha1(str(norm_repo.resolve()).encode("utf-8")).hexdigest()[:6]
    return get_edge_home() / "worktrees" / f"{norm_repo.name}-{sha1}"


def is_git_worktree_capable(repo_path: Optional[Path] = None) -> bool:
    """Return True when git is available and repo_path (if given) is a git repo."""
    if shutil.which("git") is None:
        return False
    if repo_path is None:
        return True
    return (normalize_target_path(repo_path) / ".git").exists()


def is_native_worktree_path(worktree_path: str) -> bool:
    """Return True iff worktree_path is inside EDGE_HOME/worktrees or a linked gitdir worktree."""
    if not worktree_path:
        return False
    wt = normalize_target_path(worktree_path)
    pool_base = (get_edge_home() / "worktrees").resolve()
    wt_resolved = wt.resolve()
    if wt_resolved != pool_base and wt_resolved.is_relative_to(pool_base):
        return True
    git_entry = wt / ".git"
    if wt.is_dir() and git_entry.is_file():
        return git_entry.read_text(encoding="utf-8", errors="ignore").lstrip().startswith("gitdir:")
    return False


def _parse_porcelain_worktrees(stdout: str) -> Dict[str, str]:
    """Map resolved worktree paths to checked-out branch names from porcelain output."""
    mapping: Dict[str, str] = {}
    current_wt: Optional[str] = None
    current_branch = ""
    for line in stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            if current_wt:
                mapping[current_wt] = current_branch
            current_wt, current_branch = None, ""
        elif stripped.startswith("worktree "):
            current_wt = str(Path(stripped[len("worktree "):].strip()).resolve())
        elif stripped.startswith("branch "):
            ref = stripped[len("branch "):].strip()
            current_branch = ref[len("refs/heads/"):] if ref.startswith("refs/heads/") else ref
    if current_wt:
        mapping[current_wt] = current_branch
    return mapping


def _lookup_worktree_branch(norm_repo: Path, worktree_path: str, runner: RunnerFn) -> str:
    """Look up the branch bound to worktree_path via git worktree list --porcelain."""
    code, stdout, _ = runner(["git", "worktree", "list", "--porcelain"], cwd=norm_repo, timeout=30)
    if code != 0:
        return ""
    wt_key = str(normalize_target_path(worktree_path).resolve())
    return _parse_porcelain_worktrees(stdout).get(wt_key, "")


def _remove_worktree_dir(
    norm_repo: Path, worktree_path: str, force: bool, timeout: int, runner: RunnerFn
) -> Tuple[bool, str]:
    """Remove a registered git worktree directory and prune git worktree metadata."""
    cmd = ["git", "worktree", "remove", *(["--force"] if force else []), str(worktree_path)]
    code, stdout, stderr = runner(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0 and not force:
        return False, stderr or stdout or f"git worktree remove failed (exit {code})"
    wt_dir = normalize_target_path(worktree_path)
    if force and wt_dir.exists():
        shutil.rmtree(wt_dir, ignore_errors=True)
    runner(["git", "worktree", "prune"], cwd=norm_repo, timeout=min(timeout, 30))
    return True, ""


def _preserve_aborted_branch(norm_repo: Path, branch_name: str, base_ref: str, runner: RunnerFn) -> str:
    """Rename aborted branch with commits to edge/aborted/..., or delete if empty."""
    c_code, c_out, _ = runner(["git", "rev-list", "--count", f"{base_ref}..{branch_name}"], cwd=norm_repo, timeout=15)
    ahead = int(c_out.strip()) if c_code == 0 and c_out.strip().isdigit() else 1
    if ahead > 0:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = f"edge/aborted/{sanitize_branch_dir(branch_name)}-{ts}"
        m_code, _, m_err = runner(["git", "branch", "-m", branch_name, safe_name], cwd=norm_repo, timeout=15)
        return f"Preserved aborted commits at {safe_name}." if m_code == 0 else f"Kept branch '{branch_name}': {m_err}"
    runner(["git", "branch", "-d", branch_name], cwd=norm_repo, timeout=15)
    return f"Deleted empty branch '{branch_name}'."


def _cleanup_slice_branch(
    norm_repo: Path, branch_name: str, base_branch: str, preserve_commits: bool, runner: RunnerFn
) -> str:
    """Clean up slice branch without ever losing unmerged commits."""
    if branch_name in _PROTECTED_BRANCHES or branch_name == base_branch:
        return ""
    ref_code, _, _ = runner(["git", "show-ref", "--verify", f"refs/heads/{branch_name}"], cwd=norm_repo, timeout=15)
    if ref_code != 0:
        return ""
    b_code, _, _ = runner(["git", "rev-parse", "--verify", base_branch], cwd=norm_repo, timeout=15)
    base_ref = base_branch if b_code == 0 else "HEAD"
    if preserve_commits:
        return _preserve_aborted_branch(norm_repo, branch_name, base_ref, runner)
    anc_code, _, _ = runner(["git", "merge-base", "--is-ancestor", branch_name, base_ref], cwd=norm_repo, timeout=15)
    if anc_code == 0:
        runner(["git", "branch", "-d", branch_name], cwd=norm_repo, timeout=15)
        return f"Deleted merged branch '{branch_name}'."
    return f"Kept unmerged branch '{branch_name}'."


def _validate_git_repo_head(norm_repo: Path, runner: RunnerFn) -> Optional[str]:
    """Verify norm_repo is an initialized git repository with a valid HEAD commit."""
    if not norm_repo.exists() or not (norm_repo / ".git").exists():
        return f"Target is not a valid git repository: {norm_repo}"
    h_code, _, h_err = runner(["git", "rev-parse", "--verify", "HEAD"], cwd=norm_repo, timeout=15)
    if h_code != 0:
        return f"Repository has unborn or invalid HEAD: {h_err or 'no commits'}"
    return None


def _find_active_worktrees(norm_repo: Path, branch_name: str, runner: RunnerFn) -> Tuple[Optional[str], Set[str]]:
    """Prune stale registrations and return (existing_branch_wt_or_None, active_paths)."""
    runner(["git", "worktree", "prune"], cwd=norm_repo, timeout=15)
    p_code, p_out, _ = runner(["git", "worktree", "list", "--porcelain"], cwd=norm_repo, timeout=15)
    active = _parse_porcelain_worktrees(p_out) if p_code == 0 else {}
    existing = next((wt_p for wt_p, br in active.items() if br == branch_name and Path(wt_p).is_dir()), None)
    return existing, set(active.keys())


def acquire_git_worktree(
    repo_path: Path, branch_name: str, timeout: int = 60, runner: RunnerFn = run_command
) -> Tuple[bool, str, str]:
    """Acquire or reuse an isolated native git worktree outside the repository root."""
    norm_repo = normalize_target_path(repo_path)
    if (err := _validate_git_repo_head(norm_repo, runner)) is not None:
        return False, "", err
    existing, active_paths = _find_active_worktrees(norm_repo, branch_name, runner)
    if existing:
        return True, existing, ""
    wt_path = get_repo_pool_root(norm_repo) / sanitize_branch_dir(branch_name)
    wt_path.parent.mkdir(parents=True, exist_ok=True)
    if wt_path.exists() and str(wt_path.resolve()) not in active_paths:
        shutil.rmtree(wt_path, ignore_errors=True)
    ref_code, _, _ = runner(["git", "show-ref", "--verify", f"refs/heads/{branch_name}"], cwd=norm_repo, timeout=15)
    cmd = ["git", "worktree", "add", str(wt_path), branch_name] if ref_code == 0 else ["git", "worktree", "add", "-b", branch_name, str(wt_path)]
    code, stdout, stderr = runner(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0:
        return False, "", stderr or stdout or f"git worktree add failed (exit {code})"
    return True, str(wt_path), ""


def return_git_worktree(
    repo_path: Path,
    worktree_path: str,
    force: bool = False,
    base_branch: str = "development",
    preserve_commits: bool = False,
    timeout: int = 60,
    runner: RunnerFn = run_command,
) -> Tuple[bool, str]:
    """Remove a native git worktree, prune metadata, and safely clean up its branch."""
    norm_repo = normalize_target_path(repo_path)
    if not norm_repo.exists():
        return False, f"Target repository does not exist: {norm_repo}"
    branch_name = _lookup_worktree_branch(norm_repo, worktree_path, runner)
    ok, err = _remove_worktree_dir(norm_repo, worktree_path, force, timeout, runner)
    if not ok:
        return False, err
    note = _cleanup_slice_branch(norm_repo, branch_name, base_branch, preserve_commits, runner)
    return True, f"Worktree removed. {note}".strip() if note else "Worktree removed."


def prune_git_worktrees(repo_path: Path, timeout: int = 30, runner: RunnerFn = run_command) -> Tuple[bool, str]:
    """Prune stale git worktree registrations and orphan directories under the pool root."""
    norm_repo = normalize_target_path(repo_path)
    if not norm_repo.exists():
        return False, f"Target repository does not exist: {norm_repo}"
    p_code, _, p_err = runner(["git", "worktree", "prune"], cwd=norm_repo, timeout=timeout)
    if p_code != 0:
        return False, p_err or "git worktree prune failed"
    l_code, l_out, _ = runner(["git", "worktree", "list", "--porcelain"], cwd=norm_repo, timeout=timeout)
    active = set(_parse_porcelain_worktrees(l_out).keys()) if l_code == 0 else set()
    pool_root = get_repo_pool_root(norm_repo)
    removed = 0
    if pool_root.is_dir():
        for child in pool_root.iterdir():
            if str(child.resolve()) not in active:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
    return True, f"Pruned stale git worktrees and {removed} orphan directory(ies)."


def get_git_pool_status(repo_path: Path, timeout: int = 30, runner: RunnerFn = run_command) -> Tuple[bool, str, str]:
    """Return formatted native git worktree status and pool root."""
    norm_repo = normalize_target_path(repo_path)
    code, stdout, stderr = runner(["git", "worktree", "list", "--porcelain"], cwd=norm_repo, timeout=timeout)
    if code != 0:
        return False, "", stderr or stdout
    pool_root = get_repo_pool_root(norm_repo)
    worktrees = _parse_porcelain_worktrees(stdout)
    lines: List[str] = [f"Pool Root: {pool_root}"]
    lines.extend(f"- {wt} [{br or 'detached'}]" for wt, br in worktrees.items())
    return True, "\n".join(lines), ""
