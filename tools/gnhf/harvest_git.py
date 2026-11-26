"""
Git, worktree, blocker parsing, and gate execution helpers for GNHF harvest.
"""

import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from tools.gnhf import SkippedHitlBlocker
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
    for branch in ("development", "main"):
        res = subprocess.run(
            ["git", "rev-parse", "--verify", branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return branch
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


def _read_note_blockers(n_file: Path) -> List[SkippedHitlBlocker]:
    if not n_file.exists():
        return []
    try:
        content = n_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    blockers: List[SkippedHitlBlocker] = []
    for line in content.splitlines():
        parsed = _parse_single_blocker_line(line)
        if parsed:
            blockers.append(parsed)
    return blockers


def _extract_blockers(wt_path: Path) -> List[SkippedHitlBlocker]:
    notes_candidates = [wt_path / ".gnhf" / "notes.md"]
    runs_dir = wt_path / ".gnhf" / "runs"
    if runs_dir.exists():
        notes_candidates.extend(runs_dir.glob("*/notes.md"))
    blockers: List[SkippedHitlBlocker] = []
    for n_file in notes_candidates:
        blockers.extend(_read_note_blockers(n_file))
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


def _cleanup_empty_parent_dir(worktree_path: Path) -> None:
    parent = worktree_path.parent
    if not (parent.name.endswith("-gnhf-worktrees") and parent.exists()):
        return
    try:
        if not any(parent.iterdir()):
            parent.rmdir()
    except OSError:
        pass


def _perform_cleanup(repo_path: Path, worktree_path: Path, branch_name: str) -> bool:
    subprocess.run(["git", "worktree", "remove", "--force", str(worktree_path)], cwd=repo_path, capture_output=True)
    subprocess.run(["git", "branch", "-D", branch_name], cwd=repo_path, capture_output=True)
    _cleanup_empty_parent_dir(worktree_path)
    return True
