"""Active station candidate discovery and browser invocation filters (stdlib-only)."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from tools.brigade.guard.role_detection import normalize_role
from tools.brigade.guard.transcript_scanner import TranscriptStationScanner

_AUX_AGENTS = frozenset({"browser", "browser subagent", "browser automation", "browser qa subagent"})


def is_auxiliary_tool_agent(requested_role: str) -> bool:
    """Return True for auxiliary tool subagents (e.g. browser QA)."""
    return requested_role.strip().lower() in _AUX_AGENTS


def is_active_station_for_role(info: Any, canonical: str, parent_cid: str) -> bool:
    """Return True if station record matches role, parent session, and active lifecycle."""
    if not isinstance(info, dict):
        return False
    raw_role = info.get("role") or info.get("canonicalRole") or ""
    st_role = normalize_role(raw_role) or raw_role.upper()
    info_parent = info.get("parentConversationId", "")
    if st_role != canonical or (parent_cid and info_parent and parent_cid != info_parent):
        return False
    return info.get("status", "IDLE") not in ("EXHAUSTED", "ROTATED", "TERMINATED")


def is_browser_invocation(args: Dict[str, Any]) -> bool:
    """Return True when invoke_subagent args target an auxiliary browser subagent."""
    t = str(args.get("TypeName") or args.get("typeName") or "").strip().lower()
    r = str(args.get("Role") or args.get("role") or "").strip().lower()
    return t == "browser" or is_auxiliary_tool_agent(r)


def _live_heat(scanner: Optional[TranscriptStationScanner], cid: str, tokens: int, zone: str) -> Tuple[int, str]:
    if not scanner:
        return tokens, zone
    try:
        live = scanner.calculate_subagent_heat(cid)
        if live.tokens > 0:
            return live.tokens, live.heat_zone
    except Exception:
        pass
    return tokens, zone


def collect_session_candidates(
    stations: Dict[str, Any], canonical: str, parent_cid: str, scanner: Optional[TranscriptStationScanner]
) -> List[Tuple[str, Dict[str, Any], int, str]]:
    """Collect active session registry candidates for a canonical station role."""
    out: List[Tuple[str, Dict[str, Any], int, str]] = []
    for cid, info in stations.items():
        if not is_active_station_for_role(info, canonical, parent_cid):
            continue
        heat = info.get("tokenHeat") or {}
        tok, zone = _live_heat(scanner, cid, heat.get("tokens", 0), heat.get("heatZone") or heat.get("heat_zone") or "GREEN")
        out.append((cid, info, tok, zone))
    return out


def collect_repo_candidates(
    repo_path: Optional[Union[Path, str]], canonical: str, scanner: Optional[TranscriptStationScanner]
) -> List[Tuple[str, Dict[str, Any], int, str]]:
    """Collect fallback station candidates from <repo>/.edge/brigade.json."""
    repo_file = (Path(repo_path) / ".edge" / "brigade.json") if repo_path else None
    if not repo_file or not repo_file.exists():
        return []
    try:
        rstations = json.loads(repo_file.read_text(encoding="utf-8")).get("stations", {})
    except Exception:
        return []
    if not isinstance(rstations, dict):
        return []
    out: List[Tuple[str, Dict[str, Any], int, str]] = []
    for rk, rinfo in rstations.items():
        if not isinstance(rinfo, dict):
            continue
        r_role = normalize_role(rk) or normalize_role(rinfo.get("role", "")) or str(rk).upper()
        rcid = rinfo.get("conversation_id") or rinfo.get("conversationId")
        if r_role == canonical and rcid:
            tok, zone = _live_heat(scanner, rcid, 0, "GREEN")
            out.append((rcid, rinfo, tok, zone))
    return out
