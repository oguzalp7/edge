"""
Worktree Manager Router for Edge Brigade.
Routes between Treehouse pool (primary) and native git worktree (cross-OS fallback).
Ensures zero-touch isolation of primary repository checkout during feature/refactor cycles.
"""

import json
import os
from pathlib import Path
import re
from typing import Optional, Tuple

from tools.brigade.worktree_git import (
    acquire_git_worktree,
    get_git_pool_status,
    is_git_worktree_capable,
    is_native_worktree_path,
    prune_git_worktrees,
    return_git_worktree,
)
from tools.common import normalize_target_path, run_command


def is_treehouse_installed() -> bool:
    """Checks whether the 'treehouse' CLI is installed and accessible."""
    code, _, _ = run_command(["treehouse", "--version"])
    return code == 0


def is_worktree_backend_available(repo_path: Optional[Path] = None) -> bool:
    """Return True when Treehouse or native git worktree isolation is enabled and available."""
    backend = os.environ.get("EDGE_WORKTREE_BACKEND", "").strip().lower()
    if backend == "none":
        return False
    if backend == "git":
        return is_git_worktree_capable(repo_path)
    return is_treehouse_installed() or is_git_worktree_capable(repo_path)


def _extract_treehouse_path(stdout: str) -> str:
    try:
        data = json.loads(stdout.strip())
        if isinstance(data, dict) and "path" in data:
            return str(data["path"])
    except Exception:
        pass
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    for line in lines:
        if line.startswith("/") or re.match(r"^[a-zA-Z]:[\\/]", line):
            return line
    return lines[0] if lines else ""


def _acquire_treehouse_worktree(
    norm_repo: Path, branch_name: str, lease_holder: str, timeout: int
) -> Tuple[bool, str, str]:
    cmd = ["treehouse", "get", "--lease", "-b", branch_name, "--lease-holder", lease_holder]
    code, stdout, stderr = run_command(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0:
        return False, "", f"treehouse get --lease failed (exit {code}): {stderr or stdout}"
    worktree_path = _extract_treehouse_path(stdout)
    if not worktree_path:
        return False, "", f"treehouse get succeeded but returned no worktree path in stdout. Raw: {stdout}"
    return True, worktree_path, ""


def acquire_worktree(
    repo_path: Path,
    branch_name: str,
    lease_holder: str = "edge-brigade",
    timeout: int = 60,
) -> Tuple[bool, str, str]:
    """Acquire an isolated worktree via Treehouse primary or native git worktree fallback."""
    norm_repo = normalize_target_path(repo_path)
    if not norm_repo.exists():
        return False, "", f"Target repository does not exist: {norm_repo}"
    backend = os.environ.get("EDGE_WORKTREE_BACKEND", "").strip().lower()
    if backend != "git" and is_treehouse_installed():
        return _acquire_treehouse_worktree(norm_repo, branch_name, lease_holder, timeout)
    return acquire_git_worktree(norm_repo, branch_name, timeout=timeout)


def return_worktree(
    repo_path: Path,
    worktree_path: str,
    force: bool = False,
    timeout: int = 60,
    base_branch: str = "development",
    preserve_commits: bool = False,
) -> Tuple[bool, str]:
    """Return a leased worktree to its owning backend (native git worktree or Treehouse)."""
    norm_repo = normalize_target_path(repo_path)
    if not norm_repo.exists():
        return False, f"Target repository does not exist: {norm_repo}"
    if is_native_worktree_path(worktree_path):
        return return_git_worktree(
            norm_repo,
            worktree_path,
            force=force,
            base_branch=base_branch,
            preserve_commits=preserve_commits,
            timeout=timeout,
        )
    cmd = ["treehouse", "return", *(["--force"] if force else []), worktree_path]
    code, stdout, stderr = run_command(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0:
        return False, f"treehouse return failed (exit {code}): {stderr or stdout}"
    return True, stdout or "Worktree returned to pool."


def prune_worktrees(repo_path: Path, timeout: int = 30) -> Tuple[bool, str]:
    """Prune stale worktrees and orphan directories across active backends."""
    norm_repo = normalize_target_path(repo_path)
    if not norm_repo.exists():
        return False, f"Target repository does not exist: {norm_repo}"
    return prune_git_worktrees(norm_repo, timeout=timeout)


def get_pool_status(repo_path: Path, timeout: int = 30) -> Tuple[bool, str, str]:
    """Query worktree pool status from Treehouse or native git worktree backend."""
    norm_repo = normalize_target_path(repo_path)
    backend = os.environ.get("EDGE_WORKTREE_BACKEND", "").strip().lower()
    if backend != "git" and is_treehouse_installed():
        code, stdout, stderr = run_command(["treehouse", "status"], cwd=norm_repo, timeout=timeout)
        return (True, stdout, "") if code == 0 else (False, "", stderr or stdout)
    return get_git_pool_status(norm_repo, timeout=timeout)
