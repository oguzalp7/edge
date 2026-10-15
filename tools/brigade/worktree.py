"""
Treehouse Worktree Manager for Edge Brigade.
Provides safe, deterministic git worktree allocation and pooling via Treehouse.
Ensures zero-touch isolation of primary repository checkout during feature/refactor cycles.
"""

import shutil
import json
import re
from pathlib import Path
from typing import Tuple, Dict, Any, Optional

from tools.common import normalize_target_path, run_command
from tools.common.paths import to_wsl_path


def is_treehouse_installed() -> bool:
    """Checks whether the 'treehouse' CLI is installed and accessible."""
    # Check directly via which/command -v or run_command
    code, stdout, _ = run_command(["treehouse", "--version"])
    return code == 0


def acquire_worktree(
    repo_path: Path,
    branch_name: str,
    lease_holder: str = "edge-brigade",
    timeout: int = 60,
) -> Tuple[bool, str, str]:
    """
    Acquires a durably leased worktree from the Treehouse pool.
    Runs: treehouse get --lease -b <branch_name> --lease-holder <lease_holder>
    
    Returns:
        (success: bool, worktree_path: str, error_message: str)
    """
    norm_repo = normalize_target_path(repo_path)
    if not norm_repo.exists():
        return False, "", f"Target repository does not exist: {norm_repo}"

    cmd = [
        "treehouse",
        "get",
        "--lease",
        "-b",
        branch_name,
        "--lease-holder",
        lease_holder,
    ]

    code, stdout, stderr = run_command(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0:
        err = stderr or stdout
        return False, "", f"treehouse get --lease failed (exit {code}): {err}"

    # treehouse get --lease prints the absolute worktree path to stdout.
    # Lines might contain info banners; extract the valid path line or parse JSON.
    try:
        data = json.loads(stdout.strip())
        if isinstance(data, dict) and "path" in data:
            return True, str(data["path"]), ""
    except Exception:
        pass

    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    worktree_path = ""
    for line in lines:
        # Check if line looks like an absolute path (/home/... or /... or C:\...)
        if line.startswith("/") or re.match(r"^[a-zA-Z]:[\\/]", line):
            worktree_path = line
            break

    if not worktree_path and lines:
        # Fallback to the first non-empty line
        worktree_path = lines[0]

    if not worktree_path:
        return False, "", f"treehouse get succeeded but returned no worktree path in stdout. Raw: {stdout}"

    return True, worktree_path, ""


def return_worktree(
    repo_path: Path,
    worktree_path: str,
    force: bool = False,
    timeout: int = 60,
) -> Tuple[bool, str]:
    """
    Returns a leased worktree back to the Treehouse pool.
    Terminates lingering processes and resets state.
    Runs: treehouse return [--force] <worktree_path>
    
    Returns:
        (success: bool, message: str)
    """
    norm_repo = normalize_target_path(repo_path)
    if not norm_repo.exists():
        return False, f"Target repository does not exist: {norm_repo}"

    cmd = ["treehouse", "return"]
    if force:
        cmd.append("--force")
    cmd.append(worktree_path)

    code, stdout, stderr = run_command(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0:
        err = stderr or stdout
        return False, f"treehouse return failed (exit {code}): {err}"

    return True, stdout or "Worktree returned to pool."


def get_pool_status(
    repo_path: Path,
    timeout: int = 30,
) -> Tuple[bool, str, str]:
    """
    Queries pool status from treehouse status.
    
    Returns:
        (success: bool, output: str, error_message: str)
    """
    norm_repo = normalize_target_path(repo_path)
    cmd = ["treehouse", "status"]
    code, stdout, stderr = run_command(cmd, cwd=norm_repo, timeout=timeout)
    if code != 0:
        return False, "", stderr or stdout
    return True, stdout, ""
