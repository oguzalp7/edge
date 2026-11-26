"""
Dual-Layer Refactor Ticketing & Tracker Bridge for Edge Brigade.

Pins refactor tickets strictly under target_repo/.edge/tickets/refactor/<slug>.md
(never inside leased Treehouse worktrees) and synchronizes lifecycle with
`tools.tracker` (GitHub Issues + Sub-issues or local fallback), preserving
legacy `tasks-axi` completion fallback when `issue_number` is absent.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from tools.common.fs import atomic_write_text, resolve_target_repo_root
from tools.tracker.backends import resolve_backend


def _dump_frontmatter_fallback(data: Dict[str, Any]) -> str:
    def _fmt(v: Any) -> str:
        if v is None:
            return "null"
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        return json.dumps(str(v), ensure_ascii=False)

    lines: List[str] = []
    for key, val in data.items():
        if isinstance(val, list):
            if not val:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                lines.extend(f"- {_fmt(item)}" for item in val)
        elif isinstance(val, dict):
            if not val:
                lines.append(f"{key}: {{}}")
            else:
                lines.append(f"{key}:")
                lines.extend(f"  {sub_k}: {_fmt(sub_v)}" for sub_k, sub_v in val.items())
        else:
            lines.append(f"{key}: {_fmt(val)}")
    return "\n".join(lines)


def _dump_frontmatter_yaml(frontmatter: Dict[str, Any]) -> str:
    try:
        import yaml

        return yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False).strip()
    except ImportError:
        return _dump_frontmatter_fallback(frontmatter)


def _clean_ticket_slug(slug: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (slug or "").strip().lower()).strip("-")
    return cleaned or "refactor-slice"


def _parse_tasks_axi_id(stdout: str) -> Optional[str]:
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            raw_id = parsed.get("id") or parsed.get("task_id")
            if raw_id and str(raw_id).strip():
                return str(raw_id).strip()
    except Exception:
        pass
    for line in text.splitlines():
        s = line.strip()
        if s:
            m = re.search(r"\b([a-zA-Z0-9_-]{3,})\b", s)
            if m:
                return m.group(1)
    return None


def _sync_tasks_axi_add(
    slug: str,
    track: str,
    target_rules: List[str],
    hold_captain: bool,
) -> Optional[str]:
    binary = shutil.which("tasks-axi")
    if not binary:
        return None

    rules_str = ", ".join(target_rules) if target_rules else track
    title = f"refactor({slug}): {rules_str}"
    cmd = ["tasks-axi", "add", title, "--track", track]
    if hold_captain:
        cmd.extend(["--hold", "captain"])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            return _parse_tasks_axi_id(proc.stdout)
    except Exception:
        return None
    return None


def _sync_tracker_create(
    target_repo: Path,
    clean_slug: str,
    clean_track: str,
    rules: List[str],
    files: List[str],
    targets: Dict[str, Any],
    door_type: str,
    ticket_id: str,
    parent_issue: Optional[int],
    hold_captain: bool,
    offline: bool,
) -> int:
    backend = resolve_backend(target_repo, offline=offline)
    rules_str = ", ".join(rules) if rules else clean_track
    title = f"refactor({clean_slug}): {rules_str}"
    labels = [f"track:{clean_track}", "status:ready"]
    if hold_captain:
        labels.append("hold:captain")
    body = (
        f"# Refactor Ticket: {clean_slug}\n\n"
        f"- **Ticket ID:** `{ticket_id}`\n"
        f"- **Track:** `{clean_track}`\n"
        f"- **Door Classification:** `{door_type}`\n"
        f"- **Target Rules:** {', '.join(rules) if rules else 'None'}\n"
        f"- **Target Files:** {', '.join(files) if files else 'TBD'}\n"
        f"- **Metric Targets:** `{json.dumps(targets)}`\n"
    )
    created = backend.create_issue(
        title=title,
        body=body,
        labels=labels,
        parent_number=parent_issue,
    )
    return created.number


def _render_refactor_ticket_md(
    clean_slug: str,
    clean_track: str,
    ticket_id: str,
    rules: List[str],
    files: List[str],
    targets: Dict[str, Any],
    door_type: str,
    issue_number: Optional[int],
    parent_issue: Optional[int],
) -> str:
    frontmatter = {
        "ticket_id": ticket_id,
        "slug": clean_slug,
        "track": clean_track,
        "target_rules": rules,
        "target_files": files,
        "metric_targets": targets,
        "door_type": door_type,
        "behavior_preserved": True,
        "issue_number": issue_number,
        "parent_issue": parent_issue,
        "tasks_axi_id": None,
    }
    yaml_block = _dump_frontmatter_yaml(frontmatter)
    rules_md = ", ".join(f"`{r}`" for r in rules) if rules else "_None_"
    files_md = "\n".join(f"- `{f}`" for f in files) if files else "- _TBD_"
    targets_md = "\n".join(f"- `{k}`: `{v}`" for k, v in targets.items()) if targets else "- _Non-regression_"
    issue_label = f"#{issue_number}" if issue_number is not None else "none"
    body = (
        f"# Refactor Ticket: {clean_slug}\n\n"
        f"- **Ticket ID:** `{ticket_id}`\n"
        f"- **Track:** `{clean_track}`\n"
        f"- **Door Classification:** `{door_type}`\n"
        f"- **Target Rules:** {rules_md}\n"
        f"- **Behavior Preserved:** `true`\n"
        f"- **Tracker Issue:** `{issue_label}`\n\n"
        f"## Target Files\n{files_md}\n\n"
        f"## Metric Targets\n{targets_md}\n\n"
        f"## Acceptance Criteria\n"
        f"- [ ] Preserve external behavior (`behavior_preserved: true`) and keep all tests + `tsc --noEmit` green.\n"
        f"- [ ] Respect `MigrationGate` (`src/db/schema/*` and `drizzle/*` untouched).\n"
        f"- [ ] Satisfy all `metric_targets` in `tools/gate.py --format json` and seal 4-seal `RefactorReceipt`.\n"
    )
    return f"---\n{yaml_block}\n---\n\n{body}"


def create_refactor_ticket(
    repo_path: Union[str, Path],
    slug: str,
    track: str,
    target_rules: List[str],
    target_files: List[str],
    metric_targets: Dict[str, Any],
    door_type: str = "two-way",
    sync_tasks: Optional[bool] = None,
    hold_captain: bool = False,
    parent_issue: Optional[int] = None,
    offline: bool = False,
    sync_tracker: bool = True,
) -> Tuple[bool, Path, Optional[str]]:
    """
    Atomically writes target_repo/.edge/tickets/refactor/<slug>.md with YAML frontmatter
    and optional `tools.tracker` issue linkage (`sync_tasks` overrides `sync_tracker`).
    """
    target_repo = resolve_target_repo_root(repo_path)
    clean_slug = _clean_ticket_slug(slug)
    clean_track = (track or "core").strip().lower()
    rules = [str(r).strip() for r in (target_rules or []) if str(r).strip()]
    files = [str(f).strip().replace("\\", "/") for f in (target_files or []) if str(f).strip()]
    targets = dict(metric_targets or {})
    ticket_id = f"TICK-{clean_track.upper()[:4]}-{clean_slug.upper()[:16]}"

    eff_sync = sync_tasks if sync_tasks is not None else sync_tracker
    issue_number: Optional[int] = None
    if eff_sync:
        issue_number = _sync_tracker_create(
            target_repo=target_repo, clean_slug=clean_slug, clean_track=clean_track,
            rules=rules, files=files, targets=targets, door_type=door_type,
            ticket_id=ticket_id, parent_issue=parent_issue, hold_captain=hold_captain, offline=offline,
        )

    content = _render_refactor_ticket_md(
        clean_slug=clean_slug, clean_track=clean_track, ticket_id=ticket_id,
        rules=rules, files=files, targets=targets, door_type=door_type,
        issue_number=issue_number, parent_issue=parent_issue,
    )
    ticket_path = target_repo / ".edge" / "tickets" / "refactor" / f"{clean_slug}.md"
    atomic_write_text(ticket_path, content)
    return True, ticket_path, (str(issue_number) if issue_number is not None else None)


def _complete_tracker_issue(
    repo_path: Optional[Union[str, Path]],
    issue_number: int,
    pr_url: str,
    offline: bool,
) -> Tuple[bool, str]:
    if repo_path is None:
        return False, "repo_path is required to complete tracker issue."
    backend = resolve_backend(repo_path, offline=offline)
    current = backend.get_issue(int(issue_number), include_comments=False)
    remove_labels = [lbl for lbl in ("status:ready", "status:in-progress") if lbl in current.labels]
    add_labels = ["status:done"] if "status:done" not in current.labels else []
    if remove_labels or add_labels:
        backend.edit_issue(int(issue_number), add_labels=add_labels, remove_labels=remove_labels)
    clean_url = str(pr_url).strip() if pr_url else ""
    comment = f"Completed via PR: {clean_url}" if clean_url else "Completed via Edge Brigade."
    backend.close_issue(int(issue_number), comment=comment, reason="completed")
    return True, f"Completed tracker issue #{issue_number}."


def _complete_legacy_tasks_axi(tasks_axi_id: Optional[str], pr_url: str) -> Tuple[bool, str]:
    clean_id = str(tasks_axi_id).strip() if tasks_axi_id else ""
    if not clean_id:
        return True, "No linked tasks-axi ID; skipped completion."
    if not shutil.which("tasks-axi"):
        return False, "tasks-axi binary not found; skipped task completion."
    cmd = ["tasks-axi", "done", clean_id]
    clean_url = str(pr_url).strip() if pr_url else ""
    if clean_url:
        cmd.extend(["--pr", clean_url])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            return True, proc.stdout.strip() or f"Completed tasks-axi item '{clean_id}'."
        err_msg = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
        return False, f"tasks-axi done failed: {err_msg}"
    except Exception as exc:
        return False, f"tasks-axi done unavailable: {exc}"


def complete_linked_task(
    tasks_axi_id: Optional[str],
    pr_url: str = "",
    repo_path: Optional[Union[str, Path]] = None,
    issue_number: Optional[int] = None,
    offline: bool = False,
) -> Tuple[bool, str]:
    """
    Completes a linked tracker issue (swapping status label to `status:done` and closing)
    or falls back to legacy `tasks-axi done` when `issue_number` is None.
    """
    if issue_number is not None:
        return _complete_tracker_issue(repo_path, issue_number, pr_url, offline)
    return _complete_legacy_tasks_axi(tasks_axi_id, pr_url)
