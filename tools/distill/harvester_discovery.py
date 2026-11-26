"""
Transcript discovery, parent-child station linking, and session filtering helpers.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from tools.distill.harvester_graph import (
    _append_unique_child,
    _calculate_since_cutoff_sec,
    _collect_root_candidates,
    _get_dir_mtime,
    _is_valid_sender_session,
)
from tools.distill.harvester_roles import _CID_RE, _extract_step0_role_cue, _normalize_station_role
from tools.distill.harvester_signals import _gather_subsequent_result_list


def default_brain_roots() -> List[Path]:
    home = Path.home()
    candidates = [
        home / ".gemini" / "antigravity" / "brain",
        Path("/mnt/c/Users/oguz_/.gemini/antigravity/brain"),
    ]
    env_root = os.environ.get("GEMINI_BRAIN_ROOT")
    if env_root:
        candidates.insert(0, Path(env_root))
    roots: List[Path] = []
    for c in candidates:
        if c.exists() and c not in roots:
            roots.append(c)
    return roots


def load_active_stations_map(active_stations_file: Optional[Path], set_role_fn: Callable[[str, str, int], None]) -> Dict[str, str]:
    stations_map: Dict[str, str] = {}
    if not (active_stations_file and active_stations_file.exists()):
        return stations_map
    try:
        data = json.loads(active_stations_file.read_text(encoding="utf-8"))
        for child_cid, info in data.get("stations", {}).items():
            parent_cid = info.get("parentConversationId")
            if parent_cid:
                stations_map[child_cid] = parent_cid
            role = info.get("role")
            if role:
                set_role_fn(child_cid, _normalize_station_role(str(role)), 4)
    except Exception:
        pass
    return stations_map


def discover_candidates(brain_roots: List[Path], since_hours: Optional[int]) -> List[Path]:
    candidate_dirs: List[Path] = []
    now_ts = time.time()
    cutoff_sec = _calculate_since_cutoff_sec(since_hours)
    for root in brain_roots:
        candidate_dirs.extend(_collect_root_candidates(root, now_ts, cutoff_sec))
    candidate_dirs.sort(key=_get_dir_mtime, reverse=True)
    return candidate_dirs[:100] if len(candidate_dirs) > 100 else candidate_dirs


def link_invoke_subagent_pairs(
    invoke_calls: List[Dict[str, Any]],
    res_texts: List[str],
    cid: str,
    child_to_parent: Dict[str, str],
    parent_to_children: Dict[str, List[str]],
    set_role_fn: Callable[[str, str, int], None],
) -> None:
    for tc, res_text in zip(invoke_calls, res_texts):
        m = _CID_RE.search(res_text)
        if not m:
            continue
        child_cid = m.group(1)
        if not child_cid or child_cid == cid:
            continue
        child_to_parent[child_cid] = cid
        _append_unique_child(parent_to_children, cid, child_cid)
        raw_role = str(tc.get("args", {}).get("Role", ""))
        if raw_role:
            set_role_fn(child_cid, _normalize_station_role(raw_role), 3)


def link_step_invoke_roles(
    steps: List[Dict[str, Any]],
    idx: int,
    cid: str,
    child_to_parent: Dict[str, str],
    parent_to_children: Dict[str, List[str]],
    set_role_fn: Callable[[str, str, int], None],
) -> None:
    step = steps[idx]
    tool_calls = step.get("tool_calls", [])
    invoke_calls = [tc for tc in tool_calls if tc.get("name") == "invoke_subagent"]
    if not invoke_calls:
        return
    results_list = _gather_subsequent_result_list(steps, idx)
    if len(results_list) == len(tool_calls):
        aligned = [(tc, res) for tc, res in zip(tool_calls, results_list) if tc.get("name") == "invoke_subagent"]
        link_invoke_subagent_pairs([p[0] for p in aligned], [p[1] for p in aligned], cid, child_to_parent, parent_to_children, set_role_fn)
        return
    if len(results_list) == len(invoke_calls):
        link_invoke_subagent_pairs(invoke_calls, results_list, cid, child_to_parent, parent_to_children, set_role_fn)
        return
    joined = "\n".join(results_list) + "\n" + str(step.get("content", ""))
    found_cids = [m.group(1) for m in _CID_RE.finditer(joined)]
    for tc, child_cid in zip(invoke_calls, found_cids):
        if not child_cid or child_cid == cid:
            continue
        child_to_parent[child_cid] = cid
        _append_unique_child(parent_to_children, cid, child_cid)
        raw_role = str(tc.get("args", {}).get("Role", ""))
        if raw_role:
            set_role_fn(child_cid, _normalize_station_role(raw_role), 3)


def link_parent_sender(
    steps: List[Dict[str, Any]],
    cid: str,
    child_to_parent: Dict[str, str],
    parent_to_children: Dict[str, List[str]],
    discovered_sessions: Optional[Set[str]],
    set_role_fn: Callable[[str, str, int], None],
) -> None:
    step_by_idx = {s.get("step_index"): str(s.get("content", "")) for s in steps}
    s0 = step_by_idx.get(0, "")
    s1 = step_by_idx.get(1, "")
    is_swarm = "[swarm] new board message" in s0.lower()

    if is_swarm and s1:
        m_role = re.search(r"for\s+(?:\*\*|\[)?@([a-zA-Z0-9_\-]+)(?:\*\*|\])?\s*:", s1)
        if m_role:
            set_role_fn(cid, _normalize_station_role(m_role.group(1)), 2)

    cue_role = _extract_step0_role_cue(steps)
    if cue_role:
        set_role_fn(cid, cue_role, 1)

    search_text = f"{s0}\n{s1}" if is_swarm else s0
    m_snd = re.search(r"sender=([a-zA-Z0-9_\-]+)", search_text)
    if m_snd:
        p_cid = m_snd.group(1)
        if p_cid != cid and _is_valid_sender_session(p_cid, discovered_sessions, is_swarm):
            child_to_parent[cid] = p_cid
            _append_unique_child(parent_to_children, p_cid, cid)
