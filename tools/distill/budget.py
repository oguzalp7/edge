"""Line-budget enforcement for core agents (<=60L) and profile/station rubrics (<=40L)."""

from pathlib import Path
from typing import List, Optional, Tuple


def _collect_dir_targets(p: Path) -> List[Tuple[Path, int]]:
    targets: List[Tuple[Path, int]] = []
    if (p / "agents").is_dir():
        targets.extend((f, 60) for f in sorted((p / "agents").glob("*.md")))
    if (p / ".edge" / "stations").is_dir():
        targets.extend((f, 40) for f in sorted((p / ".edge" / "stations").glob("*.md")))
    if (p / "profiles").is_dir():
        for prof_dir in sorted((p / "profiles").iterdir()):
            prof_agents = prof_dir / "agents"
            if prof_agents.is_dir():
                targets.extend((f, 40) for f in sorted(prof_agents.glob("*.md")))
    return targets


def _collect_self_targets(p: Path) -> List[Tuple[Path, int]]:
    parts = [part.lower() for part in p.parts]
    limit = 40 if ("stations" in parts or ("profiles" in parts and "agents" in parts)) else (60 if "agents" in parts else None)
    return [(f, limit) for f in sorted(p.glob("*.md"))] if limit is not None else []


def collect_budget_targets(target_path: Path) -> List[Tuple[Path, int]]:
    """Collect markdown files and their line-budget ceilings."""
    p = target_path.resolve()
    if p.is_file():
        parts = [part.lower() for part in p.parts]
        limit = 40 if ("stations" in parts or ("profiles" in parts and "agents" in parts)) else 60
        return [(p, limit)]
    return _collect_dir_targets(p) or _collect_self_targets(p)


def _evaluate_target_budgets(targets: List[Tuple[Path, int]], max_lines: Optional[int]) -> Tuple[bool, int, int]:
    all_ok, max_count, effective_limit = True, 0, max_lines or 60
    for f, def_limit in targets:
        lim = max_lines or def_limit
        cnt = len(f.read_text(encoding="utf-8", errors="replace").splitlines())
        max_count = max(max_count, cnt)
        if cnt > lim:
            all_ok, effective_limit = False, lim
    return all_ok, max_count, effective_limit


def check_line_budget(file_or_dir_path: Path, max_lines: Optional[int] = None) -> Tuple[bool, int, int]:
    """Verify agent/station/profile markdown files satisfy line-count budgets."""
    p = Path(file_or_dir_path).resolve()
    if not p.exists():
        return False, 0, max_lines or 60
    if p.is_file():
        parts = [part.lower() for part in p.parts]
        limit = max_lines if max_lines is not None else (40 if ("stations" in parts or ("profiles" in parts and "agents" in parts)) else 60)
        count = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
        return count <= limit, count, limit
    targets = collect_budget_targets(p) or [(f, max_lines or 60) for f in sorted(p.glob("*.md"))]
    return _evaluate_target_budgets(targets, max_lines) if targets else (True, 0, max_lines or 60)
