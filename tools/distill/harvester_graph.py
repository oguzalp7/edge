"""
Session graph traversal, JSONL loading, and candidate filtering for TranscriptGraphHarvester.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
_GENERIC_SENDERS = {"coordinator", "system", "user", "unknown", "parent"}


def _parse_jsonl_dict(raw_line: str) -> Optional[Dict[str, Any]]:
    line = raw_line.strip()
    if not line:
        return None
    try:
        data = json.loads(line)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _load_jsonl_steps(transcript_path: Path) -> List[Dict[str, Any]]:
    if not transcript_path.exists():
        return []
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
            return [item for raw in f if (item := _parse_jsonl_dict(raw)) is not None]
    except Exception:
        return []


def _expand_connected_session_graph(
    initial_cids: Set[str],
    parent_to_children: Dict[str, List[str]],
    child_to_parent: Dict[str, str],
) -> Set[str]:
    visited: Set[str] = set(initial_cids)
    queue: List[str] = list(initial_cids)
    while queue:
        curr = queue.pop(0)
        for child in parent_to_children.get(curr, []):
            if child and child not in visited:
                visited.add(child)
                queue.append(child)
        parent = child_to_parent.get(curr)
        if parent and parent not in visited:
            visited.add(parent)
            queue.append(parent)
    return visited


def _calculate_since_cutoff_sec(since_hours: Optional[int]) -> Optional[float]:
    return since_hours * 3600.0 if (since_hours and since_hours > 0) else None


def _get_dir_mtime(d: Path) -> float:
    try:
        return d.stat().st_mtime
    except Exception:
        return 0.0


def _is_entry_within_window(entry: Path, now_ts: float, cutoff_sec: Optional[float]) -> bool:
    if cutoff_sec is None:
        return True
    mtime = entry.stat().st_mtime if entry.exists() else 0
    return (now_ts - mtime) <= cutoff_sec


def _collect_root_candidates(root: Path, now_ts: float, cutoff_sec: Optional[float]) -> List[Path]:
    if not root.exists():
        return []
    try:
        return [
            entry for entry in root.iterdir()
            if entry.is_dir() and _is_entry_within_window(entry, now_ts, cutoff_sec)
        ]
    except Exception:
        return []


def _is_valid_sender_session(sender_id: str, discovered_sessions: Optional[Set[str]], is_swarm: bool) -> bool:
    if not sender_id or sender_id.lower() in _GENERIC_SENDERS:
        return False
    if discovered_sessions and sender_id in discovered_sessions:
        return True
    if _UUID_RE.match(sender_id):
        return True
    return not is_swarm and ("-" in sender_id or len(sender_id) >= 12)


def _append_unique_child(parent_to_children: Dict[str, List[str]], parent: str, child: str) -> None:
    children = parent_to_children.setdefault(parent, [])
    if child not in children:
        children.append(child)
