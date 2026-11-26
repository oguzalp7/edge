"""
Tracker-backed spec discovery and PR issue link formatting for Edge Ship Prep.

Keeps `tools/brigade/ship_prep.py` non-regressive on `Stage 2: Max CC` and
preserves `INV-ORCH-HOOK-LATENCY` via lazy `tools.tracker` imports.
"""

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

_CACHE_ISSUE_RE = re.compile(r"(?:^|/)\.edge/cache/issues/(\d+)\.md$")


def _read_brigade_issue_refs(repo_path: Path) -> Tuple[List[int], Optional[int], bool]:
    from tools.common.fs import resolve_target_repo_root

    roots = [resolve_target_repo_root(repo_path)]
    if repo_path not in roots:
        roots.append(repo_path)
    for root in roots:
        cfg = root / ".edge" / "brigade.json"
        if not cfg.is_file():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            continue
        ticket = data.get("active_ticket") if isinstance(data, dict) else None
        if not isinstance(ticket, dict):
            continue
        issue_num = ticket.get("issue_number")
        parent_num = ticket.get("parent_issue")
        issues = [int(issue_num)] if issue_num is not None else []
        parent = int(parent_num) if parent_num is not None else None
        return issues, parent, bool(ticket.get("tracker_offline", False))
    return [], None, False


def discover_tracker_spec_candidates(
    repo_path: Path,
    issue_numbers: Optional[List[int]] = None,
    parent_issue: Optional[int] = None,
    offline: bool = False,
) -> List[str]:
    """Fetch and cache tracker issues as `.edge/cache/issues/<N>.md` candidates.

    Falls back to `.edge/brigade.json` (`active_ticket.issue_number` /
    `parent_issue` / `tracker_offline`) when explicit args are omitted.
    """
    from tools.tracker.backends import resolve_backend
    from tools.tracker.cache import cache_issue_spec

    if issue_numbers is None and parent_issue is None:
        eff_issues, eff_parent, b_offline = _read_brigade_issue_refs(repo_path)
        eff_offline = offline or b_offline
    else:
        eff_issues = [int(n) for n in (issue_numbers or [])]
        eff_parent = int(parent_issue) if parent_issue is not None else None
        eff_offline = offline

    targets = eff_issues if eff_issues else ([eff_parent] if eff_parent is not None else [])
    if not targets:
        return []

    backend = resolve_backend(repo_path, offline=eff_offline)
    candidates: List[str] = []
    for num in dict.fromkeys(targets):
        issue = backend.get_issue(int(num), include_comments=False)
        cache_issue_spec(repo_path, issue)
        candidates.append(f".edge/cache/issues/{issue.number}.md")
    return candidates


def resolve_pr_issue_refs(
    repo_path: Path,
    issue_numbers: Optional[List[int]] = None,
    parent_issue: Optional[int] = None,
    spec_rel: Optional[str] = None,
) -> Tuple[List[int], Optional[int]]:
    """Resolve child issue numbers and optional parent issue for PR linking.

    When `spec_rel` is scoped (`--split-branches`) and points to a cached issue
    `.edge/cache/issues/<N>.md`, returns only `[N]` alongside `parent_issue`.
    """
    if issue_numbers is None and parent_issue is None:
        eff_issues, eff_parent, _ = _read_brigade_issue_refs(repo_path)
    else:
        eff_issues = [int(n) for n in (issue_numbers or [])]
        eff_parent = int(parent_issue) if parent_issue is not None else None

    if spec_rel is not None:
        match = _CACHE_ISSUE_RE.search(spec_rel.replace("\\", "/"))
        if not match:
            return [], eff_parent
        scoped_num = int(match.group(1))
        if eff_issues and scoped_num not in eff_issues:
            return [], eff_parent
        return [scoped_num], eff_parent
    return list(dict.fromkeys(eff_issues)), eff_parent


def format_pr_issue_links(
    issue_numbers: List[int],
    parent_issue: Optional[int] = None,
) -> str:
    """Render `Closes #<N>` for child tickets and `Parent Spec: #<P>` without closing parent."""
    eff_parent = int(parent_issue) if parent_issue is not None else None
    lines = [
        f"Closes #{num}"
        for num in dict.fromkeys(int(x) for x in issue_numbers)
        if num != eff_parent
    ]
    if eff_parent is not None:
        lines.append(f"Parent Spec: #{eff_parent}")
    return "\n".join(lines)
