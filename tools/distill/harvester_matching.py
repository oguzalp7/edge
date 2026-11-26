"""
Project matching and worktree alias resolution helpers for TranscriptGraphHarvester.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from tools.common.paths import to_wsl_path


def _read_json_safe(fpath: Path) -> Optional[Dict[str, Any]]:
    if not fpath.is_file():
        return None
    try:
        data = json.loads(fpath.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _normalize_match_path(raw: Optional[str]) -> str:
    """Symmetrically normalizes file:// URIs, Windows UNC paths, and WSL paths."""
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip()
    low = s.lower()
    if low.startswith("file:///\\"):
        s = s[8:]
    elif low.startswith("file://wsl.localhost/") or low.startswith("file://wsl$/"):
        s = "//" + s[7:]
    elif low.startswith("file://"):
        s = s[7:]
        if re.match(r"^/[a-zA-Z]:/", s):
            s = s[1:]
    norm = to_wsl_path(s).replace("\\", "/").rstrip("/").lower()
    return re.sub(r"^/private(?=/(?:tmp|var|etc)(?:/|$))", "", norm)


def _collect_worktree_aliases(project_path: Path) -> List[str]:
    """Collects active worktree aliases from .edge/brigade.json and .edge/checkpoint.json."""
    aliases: List[str] = []
    for rel in (".edge/brigade.json", ".edge/checkpoint.json"):
        data = _read_json_safe(project_path / rel) or {}
        ticket = data.get("active_ticket")
        wt_ticket = ticket.get("worktree_path") if isinstance(ticket, dict) else None
        for norm in (_normalize_match_path(r) for r in (data.get("active_worktree"), wt_ticket)):
            if norm and norm not in aliases:
                aliases.append(norm)
    return aliases


def _matches_treehouse_slot(text: str, project_name: str) -> bool:
    if not text or not project_name:
        return False
    norm = _normalize_match_path(text) or text.replace("\\", "/").lower()
    pname = project_name.strip().lower()
    return bool(re.search(rf"/\.treehouse/pool/[^/]+/{re.escape(pname)}(?:/|$)", norm))


def _collect_workspace_uris(steps: List[Dict[str, Any]]) -> Set[str]:
    all_uris: Set[str] = set()
    for step in steps:
        uris = step.get("workspaceUris") or step.get("workspace_uris") or []
        for u in uris:
            norm = _normalize_match_path(str(u))
            if norm:
                all_uris.add(norm)
    return all_uris


def _text_matches_targets(raw_text: str, target_strs: List[str], proj_name: str) -> bool:
    norm = _normalize_match_path(raw_text) or raw_text.replace("\\", "/").lower()
    if any(t in norm for t in target_strs):
        return True
    return _matches_treehouse_slot(norm, proj_name)


def _step_references_project(step: Dict[str, Any], target_strs: List[str], proj_name: str = "") -> bool:
    for tc in step.get("tool_calls", []):
        for val in tc.get("args", {}).values():
            if _text_matches_targets(str(val), target_strs, proj_name):
                return True
    return False


def _calculate_tool_match_ratio(steps: List[Dict[str, Any]], target_strs: List[str], proj_name: str = "") -> float:
    total = 0
    matched = 0
    for step in steps:
        if step.get("tool_calls"):
            total += 1
            if _step_references_project(step, target_strs, proj_name):
                matched += 1
    return (matched / total) if total > 0 else 0.0


def _session_matches_project(
    steps: List[Dict[str, Any]],
    project_path: Path,
    extra_project_paths: Optional[List[str]] = None,
) -> bool:
    target_strs: List[str] = []
    for raw in [str(project_path)] + list(extra_project_paths or []):
        norm = _normalize_match_path(raw)
        if norm and norm not in target_strs:
            target_strs.append(norm)
    proj_name = project_path.name.lower()

    all_uris = _collect_workspace_uris(steps)
    if all_uris:
        return any(_text_matches_targets(u, target_strs, proj_name) for u in all_uris)
    return _calculate_tool_match_ratio(steps, target_strs, proj_name) >= 0.30


def _matches_project(steps: List[Dict[str, Any]], project_path: Path) -> bool:
    return _session_matches_project(steps, project_path)
