"""
Tracker-backed cached issue spec helpers for `edge-drift`.

Isolated in a lean module (`<= 150` lines, `CC <= 10`) with lazy `tools.tracker`
imports so `discover_specs` and `consolidate` stay clean and isolated.
"""

from pathlib import Path
from typing import List, Optional


def list_cached_issue_specs(repo_path: Path) -> List[str]:
    """List `<repo_path>/.edge/cache/issues/<N>.md` paths directly without parent-repo leaks.

    Excludes `*-critique.md` and `meta.json` and avoids `resolve_target_repo_root`
    so uninitialized `tmp_path` test directories never inherit outer repo caches.
    """
    cache_dir = Path(repo_path) / ".edge" / "cache" / "issues"
    if not cache_dir.is_dir():
        return []
    results: List[str] = []
    for entry in sorted(cache_dir.glob("*.md")):
        if not entry.is_file():
            continue
        low = entry.name.lower()
        if low.endswith("-critique.md") or low == "meta.json":
            continue
        results.append(f".edge/cache/issues/{entry.name}")
    return results


def resolve_issue_source_specs(
    repo_path: Path,
    issue_numbers: Optional[List[int]] = None,
    offline: bool = False,
) -> List[Path]:
    """Fetch and cache tracker issues for `drift consolidate --issue`, fail-fast on auth error."""
    if not issue_numbers:
        return []
    from tools.tracker.backends import resolve_backend
    from tools.tracker.cache import cache_issue_spec

    backend = resolve_backend(repo_path, offline=offline)
    resolved: List[Path] = []
    for num in dict.fromkeys(int(n) for n in issue_numbers):
        issue = backend.get_issue(num, include_comments=False)
        resolved.append(cache_issue_spec(repo_path, issue))
    return resolved
