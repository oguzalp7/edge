"""
Ephemeral specification/issue cache under `<primary_root>/.edge/cache/issues/`.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Union

from tools.common.fs import atomic_write_json, atomic_write_text, resolve_target_repo_root
from .models import TrackerIssue


def ensure_cache_gitignored(repo_root: Path) -> None:
    """Idempotently ensure `.edge/cache/` (or `.edge/`) is listed in `.gitignore`."""
    gitignore = repo_root / ".gitignore"
    existing = gitignore.read_bytes().decode("utf-8") if gitignore.exists() else ""
    entries = {line.strip() for line in existing.splitlines()}
    if entries & {".edge/", ".edge", ".edge/cache/", ".edge/cache"}:
        return
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    atomic_write_text(gitignore, f"{existing}{prefix}.edge/cache/\n")


def cache_issue_spec(repo_path: Union[str, Path], issue: TrackerIssue) -> Path:
    """Write `<root>/.edge/cache/issues/<N>.md`, update `meta.json`, and gitignore cache."""
    root = resolve_target_repo_root(repo_path)
    cache_dir = root / ".edge" / "cache" / "issues"
    spec_path = cache_dir / f"{issue.number}.md"
    meta_path = cache_dir / "meta.json"

    atomic_write_text(spec_path, issue.body)
    meta: Dict[str, Any] = {}
    if meta_path.exists():
        loaded = json.loads(meta_path.read_bytes().decode("utf-8"))
        if isinstance(loaded, dict):
            meta = loaded
    meta[str(issue.number)] = {
        "number": issue.number,
        "title": issue.title,
        "state": issue.state,
        "labels": list(issue.labels),
        "url": issue.url,
        "backend": issue.backend,
        "cached_at": datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_json(meta_path, meta)
    ensure_cache_gitignored(root)
    return spec_path
