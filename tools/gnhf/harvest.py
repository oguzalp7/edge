"""
Porcelain worktree status inspection, blocker triage, and gate-verified harvest engine.
"""

import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tools.gnhf import GnhfWorktreeStatus, SkippedHitlBlocker, GnhfHarvestResult
from tools.gnhf.prompt import get_edge_gate_path


def _parse_worktree_porcelain(output: str) -> List[Dict[str, str]]:
    blocks: List[Dict[str, str]] = []
    current: Dict[str, str] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                blocks.append(current)
                current = {}
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            current[parts[0]] = parts[1]
        elif len(parts) == 1:
            current[parts[0]] = ""
    if current:
        blocks.append(current)
    return blocks


def _detect_base_branch(repo_path: Path) -> str:
    res = subprocess.run(
        ["git", "rev-parse", "--verify", "development"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        return "development"
    res_main = subprocess.run(
        ["git", "rev-parse", "--verify", "main"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if res_main.returncode == 0:
        return "main"
    return "development"


def _parse_single_blocker_line(line: str) -> Optional[SkippedHitlBlocker]:
    marker = "[SKIPPED-NEEDS-HITL]"
    if marker not in line:
        return None
    rest = line.split(marker, 1)[1].strip()
    if ":" in rest:
        file_part, reason_part = rest.split(":", 1)
        return SkippedHitlBlocker(
            file_path=file_part.strip(),
            reason=reason_part.strip(),
            raw_line=line.strip(),
        )
    return SkippedHitlBlocker(
        file_path=rest,
        reason="",
        raw_line=line.strip(),
    )


def _extract_blockers(wt_path: Path) -> List[SkippedHitlBlocker]:
    blockers: List[SkippedHitlBlocker] = []
    notes_candidates = [wt_path / ".gnhf" / "notes.md"]
    runs_dir = wt_path / ".gnhf" / "runs"
    if runs_dir.exists():
        notes_candidates.extend(runs_dir.glob("*/notes.md"))

    for n_file in notes_candidates:
        if not n_file.exists():
            continue
        try:
            content = n_file.read_text(encoding="utf-8", errors="replace")
            for line in content.splitlines():
                parsed = _parse_single_blocker_line(line)
                if parsed:
                    blockers.append(parsed)
        except Exception:
            continue
    return blockers


def _get_commit_info(wt_path: Path, base_branch: str) -> Tuple[int, str, str, str]:
    count_res = subprocess.run(
        ["git", "rev-list", "--count", f"{base_branch}..HEAD"],
        cwd=wt_path,
        capture_output=True,
        text=True,
    )
    try:
        ahead = int(count_res.stdout.strip()) if count_res.returncode == 0 else 0
    except ValueError:
        ahead = 0

    log_res = subprocess.run(
        ["git", "log", "-1", "--format=%H%x1f%s%x1f%cI"],
        cwd=wt_path,
        capture_output=True,
        text=True,
    )
    if log_res.returncode == 0 and log_res.stdout.strip():
        parts = log_res.stdout.strip().split("\x1f")
        h = parts[0] if len(parts) > 0 else ""
        s = parts[1] if len(parts) > 1 else ""
        t = parts[2] if len(parts) > 2 else ""
        return ahead, h, s, t
    return ahead, "", "", ""


def get_gnhf_status(repo_path: Path) -> List[GnhfWorktreeStatus]:
    """
    Parses 'git worktree list --porcelain', inspects commits ahead of base,
    and extracts all [SKIPPED-NEEDS-HITL] notes from .gnhf/ scratchpads.
    """
    proc = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []

    base_branch = _detect_base_branch(repo_path)
    blocks = _parse_worktree_porcelain(proc.stdout)
    results: List[GnhfWorktreeStatus] = []

    for block in blocks:
        branch_ref = block.get("branch", "")
        branch_name = branch_ref.replace("refs/heads/", "")
        if not branch_name.startswith("gnhf/"):
            continue

        wt_dir = Path(block.get("worktree", ""))
        ahead, h, s, t = _get_commit_info(wt_dir, base_branch)
        blockers = _extract_blockers(wt_dir)

        results.append(
            GnhfWorktreeStatus(
                worktree_path=wt_dir,
                branch_name=branch_name,
                base_branch=base_branch,
                commits_ahead=ahead,
                last_commit_hash=h,
                last_commit_subject=s,
                last_commit_timestamp=t,
                blockers=blockers,
            )
        )
    return results


def _run_gate(worktree_path: Path, base_branch: str, track: str) -> Tuple[bool, int, str]:
    gate_path = get_edge_gate_path()
    gate_cmd = [
        "python3",
        gate_path,
        str(worktree_path),
        "--base",
        base_branch,
        "--track",
        track,
        "--skip-verify",
    ]
    gate_res = subprocess.run(gate_cmd, capture_output=True, text=True)
    passed = gate_res.returncode == 0
    output = gate_res.stdout + (("\n" + gate_res.stderr) if gate_res.stderr else "")
    return passed, gate_res.returncode, output


def _perform_merge(repo_path: Path, base_branch: str, branch_name: str) -> Tuple[bool, Optional[str]]:
    co = subprocess.run(["git", "checkout", base_branch], cwd=repo_path, capture_output=True, text=True)
    if co.returncode != 0:
        return False, f"Checkout failed: {co.stderr}"
    mg = subprocess.run(["git", "merge", "--ff-only", branch_name], cwd=repo_path, capture_output=True, text=True)
    if mg.returncode != 0:
        return False, f"Fast-forward merge failed: {mg.stderr}"
    return True, None


def _perform_cleanup(repo_path: Path, worktree_path: Path, branch_name: str) -> bool:
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_path, capture_output=True)
    return True


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


def harvest_worktree(
    repo_path: Path,
    branch_name: Optional[str] = None,
    base_branch: str = "development",
    track: str = "all",
    merge: bool = False,
    cleanup: bool = False,
    dry_run: bool = False,
) -> GnhfHarvestResult:
    """
    Runs gate.py on the worktree, shows diff stat, and optionally executes
    clean fast-forward merge into base_branch and removes the worktree.
    """
    statuses = get_gnhf_status(repo_path)
    target = _resolve_target_worktree(statuses, branch_name)

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

    diff_res = subprocess.run(
        ["git", "diff", "--stat", f"{base_branch}...{target.branch_name}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    diff_stat = diff_res.stdout

    gate_passed, gate_code, gate_out = _run_gate(target.worktree_path, base_branch, track)
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

    if dry_run:
        return GnhfHarvestResult(
            branch_name=target.branch_name,
            base_branch=base_branch,
            gate_passed=True,
            gate_exit_code=0,
            gate_output=gate_out,
            diff_stat=diff_stat,
        )

    merged, cleaned_up, mut_err = _apply_harvest_mutations(
        repo_path, target, base_branch, merge, cleanup
    )
    if mut_err:
        return GnhfHarvestResult(
            branch_name=target.branch_name,
            base_branch=base_branch,
            gate_passed=True,
            gate_exit_code=0,
            gate_output=gate_out,
            diff_stat=diff_stat,
            error=mut_err,
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
    )
