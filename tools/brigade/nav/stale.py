"""Navigation submodule: stale link detection and annotation."""

from pathlib import Path
from typing import List

from tools.brigade.nav.constants import _DRIVE_PATH_RE
from tools.brigade.nav.links import _extract_markdown_link_targets


def _is_target_stale(target: str, containing_dir: Path, repo_root: Path) -> bool:
    if not target or target.startswith(("http://", "https://", "mailto:", "#")):
        return False
    clean = target.split("#", 1)[0].strip()
    if not clean:
        return False
    if clean.startswith("/") or _DRIVE_PATH_RE.match(clean):
        return True
    try:
        repo_resolved = repo_root.resolve()
        resolved = (containing_dir / clean).resolve()
        return not resolved.is_relative_to(repo_resolved) or not resolved.exists()
    except Exception:
        return True


def _annotate_stale_links(line: str, containing_dir: Path, repo_root: Path) -> str:
    clean_line = line.rstrip()
    for target in _extract_markdown_link_targets(clean_line):
        if _is_target_stale(target, containing_dir, repo_root):
            return f"{clean_line} [STALE]" if not clean_line.endswith("[STALE]") else clean_line
    return clean_line
