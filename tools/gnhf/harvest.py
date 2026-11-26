"""
Porcelain worktree status inspection, blocker triage, and gate-verified harvest engine.
"""

import subprocess
from pathlib import Path
from typing import List, Optional, Tuple

from tools.gnhf import GnhfHarvestResult, GnhfWorktreeStatus
from tools.gnhf.harvest_git import (
    _detect_base_branch,
    _extract_blockers,
    _get_commit_info,
    _parse_worktree_porcelain,
    _perform_cleanup,
    _perform_merge,
    _run_gate,
)


def get_gnhf_status(repo_path: Path) -> List[GnhfWorktreeStatus]:
    """Parses git worktree porcelain output and extracts .gnhf/ blockers."""
    proc = subprocess.run(["git", "worktree", "list", "--porcelain"], cwd=repo_path, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    base_branch = _detect_base_branch(repo_path)
    results: List[GnhfWorktreeStatus] = []
    for block in _parse_worktree_porcelain(proc.stdout):
        branch_name = block.get("branch", "").replace("refs/heads/", "")
        if not branch_name.startswith("gnhf/"):
            continue
        wt_dir = Path(block.get("worktree", ""))
        ahead, h, s, t = _get_commit_info(wt_dir, base_branch)
        results.append(
            GnhfWorktreeStatus(
                worktree_path=wt_dir,
                branch_name=branch_name,
                base_branch=base_branch,
                commits_ahead=ahead,
                last_commit_hash=h,
                last_commit_subject=s,
                last_commit_timestamp=t,
                blockers=_extract_blockers(wt_dir),
            )
        )
    return results


def _resolve_target_worktree(
    statuses: List[GnhfWorktreeStatus], branch_name: Optional[str]
) -> Optional[GnhfWorktreeStatus]:
    if not branch_name:
        return statuses[0] if statuses else None
    for st in statuses:
        if st.branch_name in (branch_name, f"gnhf/{branch_name}"):
            return st
    return None


def _apply_harvest_mutations(
    repo_path: Path, target: GnhfWorktreeStatus, base_branch: str, merge: bool, cleanup: bool
) -> Tuple[bool, bool, Optional[str]]:
    merged = False
    if merge:
        ok, err = _perform_merge(repo_path, base_branch, target.branch_name)
        if not ok:
            return False, False, err
        merged = True
    cleaned_up = False
    if cleanup:
        _perform_cleanup(repo_path, target.worktree_path, target.branch_name)
        cleaned_up = True
    return merged, cleaned_up, None


def _run_diff_and_gate(repo_path: Path, target: GnhfWorktreeStatus, base_branch: str, track: str) -> Tuple[str, bool, int, str]:
    diff_res = subprocess.run(
        ["git", "diff", "--stat", f"{base_branch}...{target.branch_name}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    gate_passed, gate_code, gate_out = _run_gate(target.worktree_path, base_branch, track)
    return diff_res.stdout, gate_passed, gate_code, gate_out


def harvest_worktree(
    repo_path: Path,
    branch_name: Optional[str] = None,
    base_branch: str = "development",
    track: str = "all",
    merge: bool = False,
    cleanup: bool = False,
    dry_run: bool = False,
) -> GnhfHarvestResult:
    """Runs gate.py on worktree, gathers diff stat, and optionally merges/cleans up."""
    target = _resolve_target_worktree(get_gnhf_status(repo_path), branch_name)
    resolved_branch = branch_name or (target.branch_name if target else "")
    if not target:
        return GnhfHarvestResult(
            branch_name=resolved_branch,
            base_branch=base_branch,
            gate_passed=False,
            gate_exit_code=1,
            gate_output="",
            diff_stat="",
            error=f"Worktree for branch '{resolved_branch}' not found",
        )

    diff_stat, gate_passed, gate_code, gate_out = _run_diff_and_gate(repo_path, target, base_branch, track)
    if not gate_passed:
        return GnhfHarvestResult(
            branch_name=target.branch_name,
            base_branch=base_branch,
            gate_passed=False,
            gate_exit_code=gate_code,
            gate_output=gate_out,
            diff_stat=diff_stat,
            error="Quality gate verification failed",
        )
    merged, cleaned_up, mut_err = (False, False, None) if dry_run else _apply_harvest_mutations(
        repo_path, target, base_branch, merge, cleanup
    )
    return GnhfHarvestResult(
        branch_name=target.branch_name,
        base_branch=base_branch,
        gate_passed=True,
        gate_exit_code=0,
        gate_output=gate_out,
        diff_stat=diff_stat,
        merged=merged,
        cleaned_up=cleaned_up,
        error=mut_err,
    )
