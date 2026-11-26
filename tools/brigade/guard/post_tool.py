"""Post-tool subagent/swarm registration handlers (stdlib-only)."""

import os
from pathlib import Path
from typing import Optional

from tools.brigade.guard.afk_guard import is_afk_session
from tools.brigade.guard.role_detection import extract_requested_roles, to_wsl_path
from tools.brigade.guard.station_store import register_station
from tools.brigade.guard.swarm_guard import _handle_swarm_post_tool
from tools.brigade.guard.transcript_cid import (
    extract_cid_from_payload as _extract_cid_from_payload,
    extract_cid_from_transcript_fallback as _extract_cid_from_transcript_fallback,
    fallback_would_overwrite as _fallback_would_overwrite,
)
from tools.brigade.guard.transcript_scanner import sync_repo_brigade_station


def _resolve_repo_candidate(payload: dict) -> Optional[Path]:
    candidate = payload.get("cwd") or payload.get("workspace")
    if not candidate:
        try:
            candidate = os.getcwd()
        except Exception:
            candidate = None
    rp = to_wsl_path(str(candidate)) if candidate else None
    return rp if rp and rp.exists() else None


def _handle_invoke_subagent_post_tool(payload: dict, args: dict, parent_cid: str) -> None:
    created_cid = _extract_cid_from_payload(payload)
    from_fallback = False
    if not created_cid and payload.get("transcriptPath"):
        created_cid = _extract_cid_from_transcript_fallback(payload["transcriptPath"], expected_tool="invoke_subagent")
        from_fallback = bool(created_cid)
    if not created_cid or (from_fallback and _fallback_would_overwrite(created_cid)):
        return
    roles = extract_requested_roles(args)
    role = roles[0] if roles else "STATION_WORKER"
    register_station(created_cid, role, parent_cid)
    rp = _resolve_repo_candidate(payload)
    if rp:
        sync_repo_brigade_station(rp, role, created_cid)


def handle_post_tool(payload: dict) -> dict:
    """Register newly spawned subagents/swarm workers after tool execution."""
    if is_afk_session(payload)[0]:
        return {}
    tool_call = payload.get("toolCall", {})
    tool_name, args = tool_call.get("name", ""), tool_call.get("args", {})
    parent_cid = payload.get("conversationId", "")
    if tool_name == "invoke_subagent":
        _handle_invoke_subagent_post_tool(payload, args, parent_cid)
    if tool_name == "swarm":
        _handle_swarm_post_tool(payload, args, parent_cid, _extract_cid_from_payload, _extract_cid_from_transcript_fallback, _resolve_repo_candidate)
    return {}
