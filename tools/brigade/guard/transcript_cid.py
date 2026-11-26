"""Conversation ID extraction from tool responses and transcript tail (stdlib-only)."""

import json
import re
from typing import Any, Dict, List, Optional

from tools.brigade.guard.role_detection import to_wsl_path
from tools.brigade.guard.station_store import load_active_stations

_CID_FALLBACK_RE = re.compile(r'\\?["\']conversation(?:Id|_id)\\?["\']\s*:\s*\\?["\']([a-f0-9\-]+)\\?["\']')
_CREATED_SUBAGENT_RE = re.compile(r"Created the following subagents?", re.IGNORECASE)
_SWARM_STATUS_ADDED_RE = re.compile(r'["\']status["\']\s*:\s*["\']added["\']', re.IGNORECASE)
_SKIP_FALLBACK_TYPES = frozenset({"PLANNER_RESPONSE", "USER_INPUT", "SYSTEM_MESSAGE", "EPHEMERAL_MESSAGE"})
_SKIP_FALLBACK_SOURCES = frozenset({"USER_EXPLICIT", "EPHEMERAL"})
_PROTECTED_FALLBACK_ROLES = frozenset({"", "STATION_WORKER", "SUBAGENT_GENERIC", "UNKNOWN"})


def extract_cid_from_response(resp: Any) -> Optional[str]:
    """Extract conversationId from a dict or serialized JSON/text response."""
    if isinstance(resp, dict):
        cid = resp.get("conversationId") or resp.get("conversation_id")
        return str(cid) if cid else None
    if not isinstance(resp, str):
        return None
    try:
        parsed = json.loads(resp)
        if isinstance(parsed, dict) and (parsed.get("conversationId") or parsed.get("conversation_id")):
            return str(parsed.get("conversationId") or parsed.get("conversation_id"))
    except Exception:
        pass
    match = _CID_FALLBACK_RE.search(resp)
    return match.group(1) if match else None


def extract_cid_from_payload(payload: dict) -> Optional[str]:
    """Extract conversationId from standard post-tool response keys."""
    for key in ("toolResponse", "result", "output"):
        cid = extract_cid_from_response(payload.get(key)) if payload.get(key) else None
        if cid:
            return cid
    return None


def _is_valid_fallback_step(step_obj: Any, preceding_planner: Optional[Dict[str, Any]], expected_tool: str) -> bool:
    if not isinstance(step_obj, dict):
        return False
    if step_obj.get("type") in _SKIP_FALLBACK_TYPES or step_obj.get("source") in _SKIP_FALLBACK_SOURCES:
        return False
    content = str(step_obj.get("content", ""))
    low = content.lower()
    if not low or "active subagent(s):" in low or "active subagent:" in low:
        return False
    if preceding_planner is None:
        return bool(_CREATED_SUBAGENT_RE.search(content)) or (expected_tool == "swarm" and bool(_SWARM_STATUS_ADDED_RE.search(content)))
    return any(isinstance(tc, dict) and tc.get("name") == expected_tool for tc in preceding_planner.get("tool_calls", []))


def _read_tail_dicts(transcript_path: str) -> List[Dict[str, Any]]:
    tp = to_wsl_path(transcript_path)
    if not tp.exists():
        return []
    try:
        lines = tp.read_text(encoding="utf-8", errors="ignore").splitlines()[-15:]
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    for ln in lines:
        try:
            obj = json.loads(ln)
            if isinstance(obj, dict):
                out.append(obj)
        except Exception:
            continue
    return out


def extract_cid_from_transcript_fallback(transcript_path: str, expected_tool: str = "invoke_subagent") -> Optional[str]:
    """Scan the recent transcript tail when post-tool payload omits conversationId."""
    tail = _read_tail_dicts(transcript_path)
    for idx in range(len(tail) - 1, -1, -1):
        preceding = next((tail[j] for j in range(idx - 1, -1, -1) if tail[j].get("type") == "PLANNER_RESPONSE"), None)
        if not _is_valid_fallback_step(tail[idx], preceding, expected_tool):
            continue
        match = _CID_FALLBACK_RE.search(str(tail[idx].get("content", "")))
        if match:
            return match.group(1)
    return None


def fallback_would_overwrite(created_cid: str) -> bool:
    """Return True if fallback CID is already registered under a specific non-generic role."""
    active_data = load_active_stations()
    stations = active_data.get_stations() if hasattr(active_data, "get_stations") else active_data
    existing = stations.get(created_cid) if isinstance(stations, dict) else None
    if not isinstance(existing, dict):
        return False
    role = str(existing.get("canonicalRole") or existing.get("role") or "").strip().upper()
    return role not in _PROTECTED_FALLBACK_ROLES
