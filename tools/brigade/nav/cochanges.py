"""Navigation submodule: cochanges."""

from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
import subprocess

from tools.brigade.nav.constants import _LOCKFILES

def _select_git_anchors(repo_root: Path, rel_paths: List[str]) -> List[str]:
    repo_resolved = repo_root.resolve()
    anchors: List[str] = []
    for rel in rel_paths:
        if not rel or rel.startswith("-") or rel.startswith("/"):
            continue
        try:
            candidate = (repo_root / rel).resolve()
        except Exception:
            continue
        if not (candidate.is_relative_to(repo_resolved) and candidate.exists()) or rel in anchors:
            continue
        anchors.append(rel)
        if len(anchors) >= 3:
            break
    return anchors


def _is_excluded_cochange_path(path_str: str, anchor_set: Set[str]) -> bool:
    norm = path_str.replace("\\", "/").strip()
    if not norm or norm in anchor_set:
        return True
    if norm.startswith(".edge/") or norm == ".edge":
        return True
    if norm.startswith("node_modules/") or "/node_modules/" in norm:
        return True
    return Path(norm).name in _LOCKFILES


def _run_git_lines(repo_root: Path, args: List[str]) -> List[str]:
    try:
        res = subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if res.returncode != 0 or not res.stdout.strip():
        return []
    return res.stdout.splitlines()


def _extract_git_cochanges(repo_root: Path, rel_paths: List[str], limit: int = 5) -> List[str]:
    if not (repo_root / ".git").exists():
        return []
    anchors = _select_git_anchors(repo_root, rel_paths)
    if not anchors:
        return []
    shas = [s.strip() for s in _run_git_lines(repo_root, ["log", "-n", "20", "--pretty=format:%H", "--", *anchors]) if s.strip()]
    if not shas:
        return []

    changed_lines = _run_git_lines(repo_root, ["show", "--name-only", "--pretty=format:", *shas])
    anchor_set = set(anchors)
    counts: Counter[str] = Counter()
    for line in changed_lines:
        norm = line.replace("\\", "/").strip()
        if not _is_excluded_cochange_path(norm, anchor_set):
            counts[norm] += 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [f"- {path} (co-changed {cnt}x)" for path, cnt in ranked[:limit]]
