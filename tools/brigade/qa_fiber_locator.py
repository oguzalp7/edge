"""AST component locator and frontier-axi staging for QA Fiber Inspector."""

import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _scan_file_for_component(file_path: Path, repo_path: Path, def_pattern: re.Pattern) -> Optional[Dict[str, Any]]:
    try:
        lines = file_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)
    except Exception:
        return None
    for idx, line in enumerate(lines, 1):
        if def_pattern.search(line):
            return {
                "file_path": file_path,
                "rel_path": str(file_path.relative_to(repo_path)).replace("\\", "/"),
                "def_line": idx,
                "lines": lines,
            }
    return None


def _find_exact_element_line(best: Dict[str, Any], element_text: Optional[str]) -> int:
    if not element_text or len(element_text) < 3:
        return best["def_line"]
    needle = element_text.strip().lower()
    for idx, line in enumerate(best["lines"], 1):
        if needle in line.lower():
            return idx
    return best["def_line"]


def locate_component_in_repo(repo_path: Path, component_name: str, element_text: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Locates the React component definition and line number in the target repository."""
    src_dir = (repo_path / "src") if (repo_path / "src").exists() else repo_path
    def_pattern = re.compile(
        rf"(?:export\s+(?:default\s+)?(?:function|const|class)\s+{re.escape(component_name)}\b|"
        rf"\bfunction\s+{re.escape(component_name)}\b|\bconst\s+{re.escape(component_name)}\s*[:=])"
    )
    matches: List[Dict[str, Any]] = []
    skip = ("node_modules", ".next", "dist", "build", ".git")
    for root, _, files in os.walk(src_dir):
        if any(s in root for s in skip):
            continue
        for fname in files:
            if Path(fname).suffix not in {".tsx", ".jsx", ".ts", ".js"}:
                continue
            if (hit := _scan_file_for_component(Path(root) / fname, repo_path, def_pattern)) is not None:
                matches.append(hit)
    if not matches:
        return None
    best = next((m for m in matches if component_name.lower() in m["file_path"].stem.lower()), matches[0])
    return {"component": component_name, "file": best["rel_path"], "line": _find_exact_element_line(best, element_text), "absolute_path": str(best["file_path"])}


def stage_to_frontier(
    repo_path: Path,
    file_path: str,
    line_number: int,
    component: str,
    issue: str,
    category: Optional[str] = None,
    offline: bool = False,
) -> Dict[str, Any]:
    """Stages an anomaly or visual bug into the tracker frontier (`type:frontier`, `track:ui`)."""
    from tools.tracker.backends import resolve_backend

    cat_tag = f" (#{category.lstrip('#')})" if category else ""
    title = f"[e2e-journal] {file_path}:{line_number} ({component}) - {issue}{cat_tag}"
    backend = resolve_backend(repo_path, offline=offline)

    existing = backend.list_issues(state="open", labels=["type:frontier"])
    for item in existing:
        if item.title == title or (f"{file_path}:{line_number}" in item.title and issue in item.title):
            return {
                "success": True,
                "method": f"tracker ({backend.kind}, deduped)",
                "id": str(item.number),
                "issue_number": item.number,
                "title": item.title,
                "url": item.url,
            }

    body = (
        "Automated visual anomaly detected by QA Engineer (Sommelier) during browser verification.\n\n"
        f"- **File:** `{file_path}:{line_number}`\n"
        f"- **Component:** `{component}`\n"
        f"- **Category:** `{category or 'ui'}`\n"
        f"- **Issue:** {issue}\n"
    )
    created = backend.create_issue(
        title=title,
        body=body,
        labels=["type:frontier", "track:ui", "status:ready"],
    )
    return {
        "success": True,
        "method": f"tracker ({backend.kind})",
        "id": str(created.number),
        "issue_number": created.number,
        "title": created.title,
        "url": created.url,
    }
