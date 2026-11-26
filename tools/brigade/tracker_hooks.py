"""
Modular tracker lifecycle hooks for Edge Brigade (`INV-MODULAR-FSM`).

Keeps `tools/brigade/fsm.py` lean by isolating issue-spec resolution,
in-progress labeling, pre-merge fail-fast auth preflight, and post-merge
tracker completion in a dedicated `<= 200`-line module.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Optional, Tuple

from tools.brigade.tasks_bridge import complete_linked_task
from tools.common.fs import resolve_target_repo_root
from tools.tracker.backends import resolve_backend
from tools.tracker.cache import cache_issue_spec

if TYPE_CHECKING:
    from tools.brigade.models import Ticket


def resolve_slice_issue_spec(
    repo_path: Path,
    issue_number: Optional[int],
    parent_issue: Optional[int],
    spec_path: Optional[str],
    offline: bool = False,
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Resolve and cache the spec source (`parent_issue or issue_number`) for a slice.

    Follows Captain A2: Parent Issue is the Spec SSOT while Child Issue is the
    execution ticket. When only `parent_issue` is supplied, `issue_number` stays
    `None` so finishing the slice never auto-closes the parent epic.
    """
    spec_source = parent_issue if parent_issue is not None else issue_number
    if spec_source is None:
        return spec_path, issue_number, parent_issue

    backend = resolve_backend(repo_path, offline=offline)
    issue = backend.get_issue(int(spec_source), include_comments=False)
    cached_path = cache_issue_spec(repo_path, issue)

    eff_spec_path = spec_path
    if eff_spec_path is None:
        root = resolve_target_repo_root(repo_path).resolve()
        try:
            eff_spec_path = str(cached_path.resolve().relative_to(root)).replace("\\", "/")
        except ValueError:
            eff_spec_path = str(cached_path)
    return eff_spec_path, issue_number, parent_issue


def mark_issue_in_progress(
    repo_path: Path,
    issue_number: Optional[int],
    offline: bool = False,
) -> None:
    """Transition `status:ready` -> `status:in-progress` when `issue_number` is set."""
    if issue_number is None:
        return
    backend = resolve_backend(repo_path, offline=offline)
    issue = backend.get_issue(int(issue_number), include_comments=False)
    remove_labels = ["status:ready"] if "status:ready" in issue.labels else []
    add_labels = ["status:in-progress"] if "status:in-progress" not in issue.labels else []
    if remove_labels or add_labels:
        backend.edit_issue(int(issue_number), add_labels=add_labels, remove_labels=remove_labels)


def preflight_ticket_tracker(
    repo_path: Path,
    ticket: "Ticket",
    offline: bool = False,
) -> None:
    """Verify tracker backend/auth before mutating git when `ticket.issue_number` is set."""
    if getattr(ticket, "issue_number", None) is None:
        return
    eff_offline = bool(offline or getattr(ticket, "tracker_offline", False))
    resolve_backend(repo_path, offline=eff_offline)


def complete_ticket_tracker_issue(
    repo_path: Path,
    ticket: "Ticket",
    pr_url: str = "",
    offline: bool = False,
) -> Tuple[bool, str]:
    """Complete a ticket's linked tracker issue (or legacy `tasks_axi_id`) post-merge."""
    issue_num = getattr(ticket, "issue_number", None)
    tasks_id = getattr(ticket, "tasks_axi_id", None)
    if issue_num is None and not tasks_id:
        return True, "No linked tracker issue or tasks-axi ID; skipped completion."
    eff_offline = bool(offline or getattr(ticket, "tracker_offline", False))
    try:
        return complete_linked_task(
            tasks_id,
            pr_url=pr_url,
            repo_path=repo_path,
            issue_number=issue_num,
            offline=eff_offline,
        )
    except Exception as exc:
        return False, f"Post-merge tracker completion warning: {exc}"


def warn_complete_ticket_tracker_issue(
    repo_path: Path,
    ticket: "Ticket",
    pr_url: str = "",
    offline: bool = False,
) -> None:
    """Complete a ticket's tracker issue post-merge, printing a warning on failure."""
    ok, msg = complete_ticket_tracker_issue(repo_path, ticket, pr_url=pr_url, offline=offline)
    if not ok:
        print(f"[WARN] {msg}")
