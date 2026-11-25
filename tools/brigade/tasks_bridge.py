"""
Dual-Layer Refactor Ticketing & tasks-axi Bridge for Edge Brigade.

Pins refactor tickets strictly under target_repo/.edge/tickets/refactor/<slug>.md
(never inside leased Treehouse worktrees) and optionally synchronizes lifecycle
with the external `tasks-axi` CLI, degrading gracefully when the binary is absent.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from tools.common.fs import atomic_write_text, resolve_target_repo_root


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
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return _parse_tasks_axi_id(proc.stdout)
    except Exception:
        return None
    return None


def create_refactor_ticket(
    repo_path: Union[str, Path],
    slug: str,
    track: str,
    target_rules: List[str],
    target_files: List[str],
    metric_targets: Dict[str, Any],
    door_type: str = "two-way",
    sync_tasks: bool = False,
    hold_captain: bool = False,
) -> Tuple[bool, Path, Optional[str]]:
    """
    Atomically writes target_repo/.edge/tickets/refactor/<slug>.md with YAML frontmatter
    and optional `tasks-axi` linkage. Gracefully degrades if `tasks-axi` is unavailable.
    """
    target_repo = resolve_target_repo_root(repo_path)
    clean_slug = _clean_ticket_slug(slug)
    clean_track = (track or "core").strip().lower()
    rules = [str(r).strip() for r in (target_rules or []) if str(r).strip()]
    files = [str(f).strip().replace("\\", "/") for f in (target_files or []) if str(f).strip()]
    targets = dict(metric_targets or {})

    ticket_id = f"TICK-{clean_track.upper()[:4]}-{clean_slug.upper()[:16]}"
    tasks_axi_id: Optional[str] = None
    if sync_tasks:
        tasks_axi_id = _sync_tasks_axi_add(clean_slug, clean_track, rules, hold_captain)

    frontmatter = {
        "ticket_id": ticket_id,
        "slug": clean_slug,
        "track": clean_track,
        "target_rules": rules,
        "target_files": files,
        "metric_targets": targets,
        "door_type": door_type,
        "behavior_preserved": True,
        "tasks_axi_id": tasks_axi_id,
    }
    yaml_block = yaml.safe_dump(frontmatter, sort_keys=False, default_flow_style=False).strip()

    rules_md = ", ".join(f"`{r}`" for r in rules) if rules else "_None_"
    files_md = "\n".join(f"- `{f}`" for f in files) if files else "- _TBD_"
    targets_md = "\n".join(f"- `{k}`: `{v}`" for k, v in targets.items()) if targets else "- _Non-regression_"

    body = (
        f"# Refactor Ticket: {clean_slug}\n\n"
        f"- **Ticket ID:** `{ticket_id}`\n"
        f"- **Track:** `{clean_track}`\n"
        f"- **Door Classification:** `{door_type}`\n"
        f"- **Target Rules:** {rules_md}\n"
        f"- **Behavior Preserved:** `true`\n"
        f"- **tasks-axi ID:** `{tasks_axi_id or 'none'}`\n\n"
        f"## Target Files\n{files_md}\n\n"
        f"## Metric Targets\n{targets_md}\n\n"
        f"## Acceptance Criteria\n"
        f"- [ ] Preserve external behavior (`behavior_preserved: true`) and keep all tests + `tsc --noEmit` green.\n"
        f"- [ ] Respect `MigrationGate` (`src/db/schema/*` and `drizzle/*` untouched).\n"
        f"- [ ] Satisfy all `metric_targets` in `tools/gate.py --format json` and seal 4-seal `RefactorReceipt`.\n"
    )

    content = f"---\n{yaml_block}\n---\n\n{body}"
    ticket_path = target_repo / ".edge" / "tickets" / "refactor" / f"{clean_slug}.md"
    atomic_write_text(ticket_path, content)
    return True, ticket_path, tasks_axi_id


def complete_linked_task(tasks_axi_id: Optional[str], pr_url: str = "") -> Tuple[bool, str]:
    """
    Marks a linked `tasks-axi` item done with `--pr <url>`.
    Skips safely when `tasks_axi_id` is empty and degrades gracefully when the binary is absent.
    """
    clean_id = str(tasks_axi_id).strip() if tasks_axi_id else ""
    if not clean_id:
        return True, "No linked tasks-axi ID; skipped completion."

    if not shutil.which("tasks-axi"):
        return False, "tasks-axi binary not found; skipped task completion."

    cmd = ["tasks-axi", "done", clean_id]
    if pr_url and str(pr_url).strip():
        cmd.extend(["--pr", str(pr_url).strip()])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return True, proc.stdout.strip() or f"Completed tasks-axi item '{clean_id}'."
        err_msg = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()
        return False, f"tasks-axi done failed: {err_msg}"
    except Exception as exc:
        return False, f"tasks-axi done unavailable: {exc}"
